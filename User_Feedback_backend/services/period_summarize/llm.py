"""Vertex REST wrapper for period summaries: thinking off, output cap, retries, split."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

from core.config import settings
from services.period_summarize.compact import (
    INPUT_BUDGET_TOKENS,
    estimate_tokens,
    pack_chunks,
)

logger = logging.getLogger(__name__)

THINKING_OFF = {"thinkingBudget": 0}
MAX_OUTPUT_TOKENS = 2048
MAX_ATTEMPTS = 3
MAX_SPLIT_DEPTH = 6
PAUSE_SECONDS = 0.3
BACKOFF_SECONDS = (1, 2, 4)
FLOOR_LINES = 15

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "themes": {"type": "array", "items": {"type": "string"}},
        "products": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}

SYSTEM_PROMPT = (
    "You write short executive summaries of Pidilite field-call feedback. "
    "Use only the source lines. Do not invent products, tags, or facts. "
    "Keep the summary to 120 words or fewer."
)
TIGHTER_PROMPT = "8 bullets, ≤120 words. No invented facts."


class LLMError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def _strip_fences(text_value: str) -> str:
    text_value = (text_value or "").strip()
    if text_value.startswith("```"):
        text_value = "\n".join(text_value.split("\n")[1:-1])
    return text_value.strip()


def _is_transient(status: int | None, finish: str, message: str) -> bool:
    if status in {429, 500, 503}:
        return True
    lowered = (message or "").lower()
    if "resource exhausted" in lowered or "timeout" in lowered:
        return True
    if finish in {"MAX_TOKENS", "TIMEOUT"}:
        return True
    return False


def default_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def vertex_generate(
    prompt: str,
    *,
    tighter: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """One Vertex generateContent call. Raises LLMError on failure."""
    import requests

    name = settings.GEMINI_MODEL
    project = settings.GCP_PROJECT_ID
    location = settings.GCP_LOCATION
    if not project:
        raise LLMError("fatal", "GCP_PROJECT_ID is not configured")

    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default()
    creds.refresh(google.auth.transport.requests.Request())
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project}/locations/{location}/"
        f"publishers/google/models/{name}:generateContent"
    )
    system = TIGHTER_PROMPT if tighter else SYSTEM_PROMPT
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseSchema": NARRATIVE_SCHEMA,
            "thinkingConfig": THINKING_OFF,
        },
    }
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    body = {}
    try:
        body = response.json()
    except Exception:
        body = {"error": {"message": response.text[:500]}}

    if "error" in body or response.status_code >= 400:
        err = body.get("error") or {}
        message = err.get("message") if isinstance(err, dict) else str(err)
        status = err.get("code") if isinstance(err, dict) else response.status_code
        kind = "transient" if _is_transient(status, "", str(message)) else "fatal"
        raise LLMError(kind, f"Gemini error {status}: {message}")

    candidates = body.get("candidates") or []
    if not candidates:
        raise LLMError("transient", "Gemini returned no candidates")
    candidate = candidates[0]
    finish = (candidate.get("finishReason") or candidate.get("finish_reason") or "").upper()
    if finish == "MAX_TOKENS":
        raise LLMError("max_tokens", "finishReason=MAX_TOKENS")
    if finish == "TIMEOUT":
        raise LLMError("transient", "finishReason=TIMEOUT")
    try:
        raw = candidate["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("transient", f"missing text (finishReason={finish or 'unknown'})") from exc

    raw = _strip_fences(raw)
    usage = body.get("usageMetadata") or {}
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise LLMError("malformed", f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not str(parsed.get("summary") or "").strip():
        raise LLMError("malformed", "JSON missing summary")
    parsed["_tokens"] = {
        "input": usage.get("promptTokenCount", 0),
        "output": usage.get("candidatesTokenCount", 0),
    }
    return parsed


GenerateFn = Callable[..., dict[str, Any]]
SleepFn = Callable[[float], None]


def _assert_under_budget(prompt: str) -> None:
    if estimate_tokens(prompt) > INPUT_BUDGET_TOKENS:
        raise LLMError("fatal", "prompt exceeds input token budget")


def _call_with_retries(
    generate: GenerateFn,
    prompt: str,
    *,
    tighter: bool,
    sleep: SleepFn,
) -> dict[str, Any]:
    _assert_under_budget(prompt)
    last_error: Optional[LLMError] = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            result = generate(prompt, tighter=tighter)
            sleep(PAUSE_SECONDS)
            return result
        except LLMError as exc:
            last_error = exc
            if exc.kind == "max_tokens":
                raise
            if exc.kind == "malformed" and attempt == 0:
                sleep(PAUSE_SECONDS)
                continue
            if exc.kind == "transient" and attempt < MAX_ATTEMPTS - 1:
                sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            raise
        except Exception as exc:
            last_error = LLMError("transient", str(exc))
            if attempt < MAX_ATTEMPTS - 1:
                sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            raise last_error from exc
    raise last_error or LLMError("fatal", "LLM failed")


def _prompt_for(
    lines: list[str],
    tighter: bool,
    *,
    grain: Optional[str] = None,
    grain_label: Optional[str] = None,
) -> str:
    header = TIGHTER_PROMPT if tighter else (
        "Summarize these compact feedback lines. "
        "Return JSON with summary, themes, products, risks. ≤120 words."
    )
    if grain == "tag":
        label = (grain_label or "").strip() or "this tag"
        if tighter:
            header = f"For tag '{label}' only. {TIGHTER_PROMPT} The narrative must justify this tag."
        else:
            header = (
                f"Summarize these compact feedback lines for the tag '{label}'. "
                "The narrative must justify this tag — every theme should relate to it. "
                "Use only the source lines. Do not invent products, tags, or facts. "
                "Return JSON with summary, themes, products, risks. ≤120 words."
            )
    return header + "\n\n" + "\n".join(lines)


def summarize_lines(
    lines: list[str],
    *,
    generate: GenerateFn = vertex_generate,
    sleep: SleepFn = default_sleep,
    grain: Optional[str] = None,
    grain_label: Optional[str] = None,
) -> dict[str, Any]:
    """Map-reduce lines under the 8k input budget. Adaptive split on MAX_TOKENS."""
    if not lines:
        return {
            "summary": "No insights for this period.",
            "themes": [],
            "products": [],
            "risks": [],
            "_tokens": {"input": 0, "output": 0},
            "_truncated": False,
        }

    chunks, truncated = pack_chunks(lines)
    partials: list[dict[str, Any]] = []
    total_in = 0
    total_out = 0

    def _fallback_narrative(items: list[dict[str, Any]], extra: str = "") -> dict[str, Any]:
        summaries = [str(item.get("summary") or "").strip() for item in items]
        summaries = [text for text in summaries if text]
        themes: list[str] = []
        products: list[str] = []
        risks: list[str] = []
        for item in items:
            themes.extend(item.get("themes") or [])
            products.extend(item.get("products") or [])
            risks.extend(item.get("risks") or [])
        summary = " ".join(summaries).strip()
        if extra and not summary:
            summary = extra
        if not summary:
            summary = "Summary truncated after retry cap."
        return {
            "summary": summary[:1200],
            "themes": list(dict.fromkeys(themes))[:12],
            "products": list(dict.fromkeys(products))[:12],
            "risks": list(dict.fromkeys(risks))[:8],
            "_tokens": {"input": 0, "output": 0},
            "_truncated": True,
        }

    def _summarize_chunk(chunk: list[str], tighter: bool = False, depth: int = 0) -> dict[str, Any]:
        if depth > MAX_SPLIT_DEPTH:
            raise LLMError("fatal", "split depth cap")
        prompt = _prompt_for(chunk, tighter, grain=grain, grain_label=grain_label)
        try:
            return _call_with_retries(generate, prompt, tighter=tighter, sleep=sleep)
        except LLMError as exc:
            if exc.kind == "max_tokens" and len(chunk) > 1 and depth < MAX_SPLIT_DEPTH:
                mid = max(1, len(chunk) // 2)
                left = _summarize_chunk(chunk[:mid], tighter, depth + 1)
                right = _summarize_chunk(chunk[mid:], tighter, depth + 1)
                return _merge_partials([left, right], tighter=tighter, depth=depth + 1)
            if exc.kind == "max_tokens" and not tighter and depth < MAX_SPLIT_DEPTH:
                return _summarize_chunk(chunk, tighter=True, depth=depth + 1)
            if exc.kind == "max_tokens" and len(chunk) > 1:
                return _fallback_narrative([{"summary": " ".join(chunk[:FLOOR_LINES])}])
            raise

    def _merge_partials(items: list[dict[str, Any]], tighter: bool = False, depth: int = 0) -> dict[str, Any]:
        if len(items) == 1:
            return items[0]
        if depth > MAX_SPLIT_DEPTH:
            return _fallback_narrative(items)
        merged_lines = []
        for item in items:
            summary = str(item.get("summary") or "").strip()
            if summary:
                merged_lines.append(summary)
        if not merged_lines:
            return _fallback_narrative(items)
        prompt = _prompt_for(merged_lines, tighter, grain=grain, grain_label=grain_label)
        try:
            return _call_with_retries(generate, prompt, tighter=tighter, sleep=sleep)
        except LLMError as exc:
            if exc.kind == "max_tokens" and len(merged_lines) > 1 and depth < MAX_SPLIT_DEPTH:
                mid = max(1, len(merged_lines) // 2)
                left = _merge_partials(
                    [{"summary": line} for line in merged_lines[:mid]],
                    tighter=True,
                    depth=depth + 1,
                )
                right = _merge_partials(
                    [{"summary": line} for line in merged_lines[mid:]],
                    tighter=True,
                    depth=depth + 1,
                )
                return _merge_partials([left, right], tighter=True, depth=depth + 1)
            if exc.kind == "max_tokens":
                return _fallback_narrative(items)
            raise

    for chunk in chunks:
        partial = _summarize_chunk(chunk)
        tokens = partial.get("_tokens") or {}
        total_in += int(tokens.get("input") or 0)
        total_out += int(tokens.get("output") or 0)
        partials.append(partial)

    result = _merge_partials(partials) if len(partials) > 1 else partials[0]
    tokens = result.get("_tokens") or {}
    result["_tokens"] = {
        "input": total_in + int(tokens.get("input") or 0) if len(partials) > 1 else int(tokens.get("input") or 0),
        "output": total_out + int(tokens.get("output") or 0) if len(partials) > 1 else int(tokens.get("output") or 0),
    }
    if len(partials) == 1:
        result["_tokens"] = {
            "input": int(tokens.get("input") or 0),
            "output": int(tokens.get("output") or 0),
        }
    result["_truncated"] = truncated
    return result
