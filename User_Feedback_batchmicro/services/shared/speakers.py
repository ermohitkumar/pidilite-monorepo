"""Assign FME (Pidilite rep) and User (customer) for the whole call.

STT speaker tags (when present) are anonymous acoustic IDs, not roles.
Gemini also guesses per-turn and often flips identity mid-conversation.
This module remaps labels globally using FME vs customer language cues,
then emits FME: / User: (Speaker 1 / Speaker 2 are treated as aliases).
"""
from __future__ import annotations

import re

_TURN_RE = re.compile(
    r"^(?:Speaker\s+(\d+)|(FME|User|Customer|Dealer|Contractor|Carpenter))\s*:\s*(.*)$",
    re.IGNORECASE,
)
_NAME_TO_ID = {
    "fme": 1,
    "user": 2,
    "customer": 2,
    "dealer": 2,
    "contractor": 2,
    "carpenter": 2,
}
_ID_TO_LABEL = {1: "FME", 2: "User"}
_LABEL_STRIP_RE = re.compile(
    r"(?:speaker\s+\d+|fme|user|dealer|customer|contractor|carpenter)\s*:",
    re.IGNORECASE,
)

_FME_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwe will\b",
        r"\bwe'll\b",
        r"\bi will arrange\b",
        r"\bi'll arrange\b",
        r"\bour company\b",
        r"\bpidilite\b",
        r"\bfcc\b",
        r"\bproduct team\b",
        r"\bour product\b",
        r"\bour side\b",
        r"\bfrom our side\b",
        r"\bnoted\b",
        r"\bhow is\b",
        r"\bwhat about\b",
        r"\bdo you\b",
        r"\bare you using\b",
        r"\bany (issue|problem)\b",
        r"\bi understand\b",
        r"\bwe can send\b",
        r"\bwe will send\b",
        r"\btrial (material|pack|tin|sample)\b",
        r"\bscheme\b",
        r"\bwe will raise\b",
        r"\bi'll raise\b",
        r"\bfrom pidilite\b",
    )
]

_CUSTOMER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bi applied\b",
        r"\bwe applied\b",
        r"\bhad applied\b",
        r"\bi use\b",
        r"\bwe use\b",
        r"\bi ordered\b",
        r"\bwe ordered\b",
        r"\bmy site\b",
        r"\bour site\b",
        r"\bleak",
        r"\bbubbl",
        r"\bnot dry",
        r"\bproblem with\b",
        r"\bi am having\b",
        r"\bwe buy\b",
        r"\bi buy\b",
        r"\bcredit days\b",
        r"\bcompetitor\b",
        r"\bcompetition\b",
        r"\bmy dealer\b",
        r"\bthe client said\b",
    )
]

# Only swap 1↔2 when the other speaker is clearly more FME-like.
_SWAP_MARGIN = 2


def parse_turns(text: str) -> list[tuple[int | None, str]]:
    """Split labeled transcript into (speaker_id, utterance) turns."""
    turns: list[tuple[int | None, str]] = []
    current_id: int | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_id, current_parts
        body = " ".join(current_parts).strip()
        if body:
            turns.append((current_id, body))
        current_id = None
        current_parts = []

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _TURN_RE.match(line)
        if match:
            flush()
            if match.group(1):
                current_id = int(match.group(1))
            else:
                current_id = _NAME_TO_ID.get((match.group(2) or "").lower(), 2)
            rest = (match.group(3) or "").strip()
            current_parts = [rest] if rest else []
            continue
        if current_id is not None:
            current_parts.append(line)
        else:
            turns.append((None, line))
    flush()
    return turns


def merge_consecutive(turns: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    merged: list[tuple[int | None, str]] = []
    for sid, body in turns:
        if not body:
            continue
        if merged and merged[-1][0] == sid and sid is not None:
            merged[-1] = (sid, f"{merged[-1][1]} {body}")
        else:
            merged.append((sid, body))
    return merged


def format_turns(turns: list[tuple[int | None, str]]) -> str:
    lines: list[str] = []
    for sid, body in merge_consecutive(turns):
        if sid is None:
            lines.append(body)
        else:
            lines.append(f"{_ID_TO_LABEL.get(sid, f'Speaker {sid}')}: {body}")
    return "\n".join(lines)


def score_role(text: str) -> tuple[int, int]:
    """Return (fme_score, customer_score) for one utterance."""
    fme = sum(1 for pattern in _FME_PATTERNS if pattern.search(text))
    customer = sum(1 for pattern in _CUSTOMER_PATTERNS if pattern.search(text))
    fme += text.count("?")
    return fme, customer


def _net_fme(stats: dict[str, int]) -> int:
    return stats["fme"] - stats["cust"]


def _should_swap_roles(by_id: dict[int, dict[str, int]]) -> bool:
    if 1 not in by_id or 2 not in by_id:
        return False
    return (_net_fme(by_id[2]) - _net_fme(by_id[1])) >= _SWAP_MARGIN


def _mapped_speaker_id(
    sid: int, swap: bool, by_id: dict[int, dict[str, int]]
) -> int:
    if swap and sid in (1, 2):
        return 2 if sid == 1 else 1
    if sid not in (1, 2):
        return 1 if _net_fme(by_id.get(sid, {"fme": 0, "cust": 0})) > 0 else 2
    return sid


def remap_speaker_roles(text: str) -> str:
    """Map the FME cluster to FME: and the customer cluster to User:.

    Does not re-split mixed turns. A dedicated LLM relabel pass should run first
    so each line belongs to one person; this only corrects a global 1↔2 inversion.
    """
    turns = parse_turns(text)
    by_id: dict[int, dict[str, int]] = {}
    for sid, body in turns:
        if sid is None:
            continue
        fme, customer = score_role(body)
        agg = by_id.setdefault(sid, {"fme": 0, "cust": 0})
        agg["fme"] += fme
        agg["cust"] += customer

    swap = _should_swap_roles(by_id)
    remapped: list[tuple[int | None, str]] = []
    for sid, body in turns:
        if sid is None:
            remapped.append((None, body))
        else:
            remapped.append((_mapped_speaker_id(sid, swap, by_id), body))
    return format_turns(remapped)


_COLLAPSE_MIN_CHARS = 300
_COLLAPSE_MAX_LINES = 3
_COLLAPSE_LONG_LINE = 400


def is_collapsed_speaker_transcript(text: str) -> bool:
    """True when a two-person call was dumped onto one speaker / a few long lines.

    remap_speaker_roles cannot invent User turns from a single Speaker 1 blob.
    """
    turns = parse_turns(text)
    if not turns:
        return False
    bodies = [body for _, body in turns if body]
    total = sum(len(body) for body in bodies)
    if total < _COLLAPSE_MIN_CHARS:
        return False
    speaker_ids = {sid for sid, _ in turns if sid is not None}
    n_lines = len([ln for ln in (text or "").splitlines() if ln.strip()])
    if len(speaker_ids) >= 2 and n_lines >= 4:
        return False
    if n_lines <= _COLLAPSE_MAX_LINES:
        return True
    return any(len(body) >= _COLLAPSE_LONG_LINE for body in bodies)


def content_preserved(original: str, candidate: str, min_ratio: float = 0.8) -> bool:
    """True when candidate still has most of the spoken words (labels ignored)."""

    def words(value: str) -> list[str]:
        cleaned = _LABEL_STRIP_RE.sub(" ", value or "")
        return cleaned.split()

    original_words = words(original)
    if not original_words:
        return bool(words(candidate))
    return len(words(candidate)) >= len(original_words) * min_ratio
