"""Vertex REST wrapper for period summaries: thinking off, output cap, retries, split."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
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
MAX_ATTEMPTS = 5
MAX_SPLIT_DEPTH = 6
PAUSE_SECONDS = 0.3
BACKOFF_SECONDS = (1, 2, 4, 8, 16)
MAX_RETRY_WAIT = 30
FLOOR_LINES = 15
TRANSIENT_HTTP = {408, 409, 425, 429, 499, 500, 502, 503, 504}
TRANSIENT_GRPC = {4, 8, 10, 13, 14}  # DEADLINE_EXCEEDED, RESOURCE_EXHAUSTED, ABORTED, INTERNAL, UNAVAILABLE
TRANSIENT_MARKERS = (
    "resource exhausted",
    "unavailable",
    "deadline",
    "timeout",
    "rate limit",
    "too many requests",
    "quota",
    "temporarily",
    "connection reset",
    "connection aborted",
    "503",
    "502",
    "429",
)

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "data": {"type": "string"},
                    "quotes": {"type": "array", "items": {"type": "string"}},
                    "user_count": {"type": "integer"},
                },
                "required": ["title", "data"],
            },
        },
        "themes": {"type": "array", "items": {"type": "string"}},
        "products": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}

SYSTEM_PROMPT = (
    "You write numbered field-feedback findings for Pidilite. "
    "Use only the source lines. Do not invent products, tags, quotes, or counts. "
    "Each finding has a short title, a Data line with unique mention counts and regions, "
    "and complete verbatim quotes. Do not truncate quotes or titles. "
    "Example:\n"
    "1. Barcode fraud on loyalty points — RELAM, NFU and Ezee Spray.\n\n"
    "Data: 88 unique contractor mentions across multiple regions. Pattern: exposed barcodes.\n\n"
    "· \"EVERY FCCR POINTS MUST BE SILVER COATED — RBDM-NASIK\"\n"
)
TIGHTER_PROMPT = "Numbered findings with Data and complete quotes. No invented facts."


class LLMError(Exception):
    def __init__(self, kind: str, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retry_after = retry_after


class GeminiGate:
    """Process-wide cap on in-flight Vertex calls and queries per minute."""

    def __init__(
        self,
        max_in_flight: int = 2,
        max_per_minute: int = 60,
        min_interval: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_in_flight = max(1, int(max_in_flight))
        self.max_per_minute = max(1, int(max_per_minute))
        self.min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._lock = threading.Lock()
        self._in_flight = 0
        self._starts: deque[float] = deque()
        self._last = 0.0

    def acquire(self, sleep: Callable[[float], None]) -> None:
        while True:
            with self._lock:
                now = self._clock()
                while self._starts and now - self._starts[0] >= 60.0:
                    self._starts.popleft()
                if self._in_flight >= self.max_in_flight:
                    wait = 0.05
                elif len(self._starts) >= self.max_per_minute:
                    wait = min(max(60.0 - (now - self._starts[0]), 0.05), 5.0)
                else:
                    gap = now - self._last
                    if gap < self.min_interval:
                        wait = self.min_interval - gap
                    else:
                        self._in_flight += 1
                        self._starts.append(now)
                        self._last = now
                        return
            sleep(max(wait, 0.01))

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)


_gate: Optional[GeminiGate] = None
_gate_lock = threading.Lock()


def get_gate() -> GeminiGate:
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = GeminiGate(
                max_in_flight=settings.PERIOD_SUMMARY_MAX_CONCURRENT,
                max_per_minute=settings.PERIOD_SUMMARY_MAX_PER_MINUTE,
                min_interval=settings.PERIOD_SUMMARY_MIN_INTERVAL_SECONDS,
            )
        return _gate


def _strip_fences(text_value: str) -> str:
    text_value = (text_value or "").strip()
    if text_value.startswith("```"):
        text_value = "\n".join(text_value.split("\n")[1:-1])
    return text_value.strip()


def _is_transient(
    status: int | str | None,
    finish: str,
    message: str,
    status_name: str = "",
) -> bool:
    if isinstance(status, int) and (status in TRANSIENT_HTTP or status in TRANSIENT_GRPC):
        return True
    blob = " ".join([str(status or ""), status_name, finish, message]).lower()
    return any(marker in blob for marker in TRANSIENT_MARKERS)


def _retry_after_seconds(response: Any, body: dict[str, Any]) -> Optional[float]:
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw:
        try:
            return min(float(raw), MAX_RETRY_WAIT)
        except (TypeError, ValueError):
            pass
    err = body.get("error") if isinstance(body, dict) else None
    details = err.get("details") if isinstance(err, dict) else None
    for item in details or []:
        if not isinstance(item, dict):
            continue
        delay = item.get("retryDelay") or item.get("retry_delay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return min(float(delay[:-1]), MAX_RETRY_WAIT)
            except ValueError:
                continue
        if isinstance(delay, dict) and delay.get("seconds") is not None:
            try:
                return min(float(delay["seconds"]), MAX_RETRY_WAIT)
            except (TypeError, ValueError):
                continue
    return None


def _retry_wait(attempt: int, retry_after: Optional[float]) -> float:
    exponential = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
    if retry_after and retry_after > 0:
        return min(max(retry_after, exponential * 0.5), MAX_RETRY_WAIT)
    return min(exponential, MAX_RETRY_WAIT)


def default_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _bearer_token() -> str:
    """Resolve an access token without the optional `requests` / `google-auth` stack.

    Prefer the GCE/Cloud Run metadata server (always present in deployed runtimes).
    Fall back to Application Default Credentials when google-auth is installed (local).
    """
    import httpx

    try:
        response = httpx.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
            timeout=5.0,
        )
        if response.status_code == 200:
            token = (response.json() or {}).get("access_token")
            if token:
                return str(token)
    except Exception:
        pass

    try:
        import google.auth
        from google.auth.transport.requests import Request as GoogleAuthRequest
    except ImportError as exc:
        raise LLMError("fatal", "no access token source (metadata + google-auth missing)") from exc

    creds, _ = google.auth.default()
    creds.refresh(GoogleAuthRequest())
    if not creds.token:
        raise LLMError("fatal", "ADC returned empty access token")
    return str(creds.token)


def vertex_generate(
    prompt: str,
    *,
    tighter: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """One Vertex generateContent call. Raises LLMError on failure."""
    import httpx

    name = settings.GEMINI_MODEL
    project = settings.GCP_PROJECT_ID
    location = settings.GCP_LOCATION
    if not project:
        raise LLMError("fatal", "GCP_PROJECT_ID is not configured")

    token = _bearer_token()
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
    gate = get_gate()
    gate.acquire(default_sleep)
    try:
        try:
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMError("transient", f"Gemini timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError("transient", f"Gemini request failed: {exc}") from exc
        body = {}
        try:
            body = response.json()
        except Exception:
            body = {"error": {"message": (response.text or "")[:500]}}

        if "error" in body or response.status_code >= 400:
            err = body.get("error") or {}
            message = err.get("message") if isinstance(err, dict) else str(err)
            status_name = str(err.get("status") or "") if isinstance(err, dict) else ""
            err_code = err.get("code") if isinstance(err, dict) else response.status_code
            retry_after = _retry_after_seconds(response, body)
            kind = "transient" if (
                _is_transient(response.status_code, "", str(message), status_name)
                or _is_transient(err_code, "", str(message), status_name)
            ) else "fatal"
            raise LLMError(kind, f"Gemini error {response.status_code}: {message}", retry_after=retry_after)

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
    finally:
        gate.release()


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
                wait = _retry_wait(attempt, exc.retry_after)
                logger.warning(
                    "period summary LLM retry attempt=%s/%s wait=%.1fs: %s",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    wait,
                    exc.message,
                )
                sleep(wait)
                continue
            raise
        except Exception as exc:
            last_error = LLMError("transient", str(exc))
            if attempt < MAX_ATTEMPTS - 1:
                wait = _retry_wait(attempt, None)
                logger.warning(
                    "period summary LLM retry attempt=%s/%s wait=%.1fs: %s",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    wait,
                    exc,
                )
                sleep(wait)
                continue
            raise last_error from exc
    raise last_error or LLMError("fatal", "LLM failed")


def _prompt_for(
    lines: list[str],
    tighter: bool,
    *,
    grain: Optional[str] = None,
    grain_label: Optional[str] = None,
    previous_summary: Optional[str] = None,
) -> str:
    if previous_summary:
        header = (
            "Update the existing period summary using only the new compact feedback lines. "
            "Keep prior findings that still apply. Fold in new evidence. "
            "Write numbered findings with a Data line and complete quotes. "
            "Return JSON with summary and findings."
        )
        if tighter:
            header = "Update the prior summary with the new lines only. " + TIGHTER_PROMPT
        if grain == "tag":
            label = (grain_label or "").strip() or "this tag"
            header = (
                f"Update the existing summary for tag '{label}' using only the new lines. "
                "Keep prior findings that still apply. The narrative must justify this tag. "
                "Return JSON with summary and findings."
            )
        return (
            header
            + "\n\nPrevious summary:\n"
            + previous_summary.strip()
            + "\n\nNew feedback lines:\n"
            + "\n".join(lines)
        )

    header = TIGHTER_PROMPT if tighter else (
        "Summarize these compact site-visit feedback lines by theme as numbered findings. "
        "Count mentions per theme. When a line has others:, include that note for the Others theme. "
        "Each finding needs a title, a Data line with unique mention counts and regions, "
        "and complete verbatim quotes. Do not truncate. "
        "Return JSON with summary and findings."
    )
    if grain == "tag":
        label = (grain_label or "").strip() or "this tag"
        if tighter:
            header = f"For tag '{label}' only. {TIGHTER_PROMPT} The narrative must justify this tag."
        else:
            header = (
                f"Summarize these compact feedback lines for the tag '{label}'. "
                "The narrative must justify this tag. "
                "Write numbered findings with a Data line and complete quotes. "
                "Use only the source lines. Do not invent products, tags, or facts. "
                "Return JSON with summary and findings."
            )
    return header + "\n\n" + "\n".join(lines)


def summarize_lines(
    lines: list[str],
    *,
    generate: GenerateFn = vertex_generate,
    sleep: SleepFn = default_sleep,
    grain: Optional[str] = None,
    grain_label: Optional[str] = None,
    previous_summary: Optional[str] = None,
) -> dict[str, Any]:
    """Map-reduce lines under the 8k input budget. Adaptive split on MAX_TOKENS."""
    if not lines and not previous_summary:
        return {
            "summary": "No insights for this period.",
            "themes": [],
            "products": [],
            "risks": [],
            "_tokens": {"input": 0, "output": 0},
            "_truncated": False,
        }
    if previous_summary and not lines:
        return {
            "summary": previous_summary,
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

    def _summarize_chunk(
        chunk: list[str],
        tighter: bool = False,
        depth: int = 0,
        *,
        with_previous: bool = False,
    ) -> dict[str, Any]:
        if depth > MAX_SPLIT_DEPTH:
            raise LLMError("fatal", "split depth cap")
        prior = previous_summary if with_previous else None
        prompt = _prompt_for(
            chunk,
            tighter,
            grain=grain,
            grain_label=grain_label,
            previous_summary=prior,
        )
        try:
            return _call_with_retries(generate, prompt, tighter=tighter, sleep=sleep)
        except LLMError as exc:
            if exc.kind == "max_tokens" and len(chunk) > 1 and depth < MAX_SPLIT_DEPTH:
                mid = max(1, len(chunk) // 2)
                left = _summarize_chunk(chunk[:mid], tighter, depth + 1, with_previous=with_previous)
                right = _summarize_chunk(chunk[mid:], tighter, depth + 1, with_previous=False)
                return _merge_partials([left, right], tighter=tighter, depth=depth + 1)
            if exc.kind == "max_tokens" and not tighter and depth < MAX_SPLIT_DEPTH:
                return _summarize_chunk(chunk, tighter=True, depth=depth + 1, with_previous=with_previous)
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

    for index, chunk in enumerate(chunks):
        partial = _summarize_chunk(chunk, with_previous=(index == 0 and bool(previous_summary)))
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
