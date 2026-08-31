"""Snap LLM verbatim quotes back onto the exact transcript text."""
from __future__ import annotations

import re

_SPEAKER_LABEL_RE = re.compile(
    r"^(Speaker\s+\d+|FME|User|Dealer|Customer|Contractor|Carpenter)\s*[:\-–—]\s*",
    re.IGNORECASE,
)


def _fold_char(ch: str) -> str:
    if ch == "\u00a0":
        return " "
    if ch.isupper():
        return ch.lower()
    if ch in "’‘`":
        return "'"
    if ch in "“”":
        return '"'
    if ch in "–—-":
        return " "
    if re.match(r"[a-z0-9\u0900-\u097f']", ch):
        return ch
    return " "


def _fold(text: str) -> tuple[str, list[int]]:
    folded: list[str] = []
    mapping: list[int] = []
    last_space = True
    for index, ch in enumerate(text or ""):
        next_ch = _fold_char(ch)
        if next_ch == " ":
            if last_space or not folded:
                continue
            last_space = True
            folded.append(" ")
            mapping.append(index)
            continue
        last_space = False
        folded.append(next_ch)
        mapping.append(index)
    while folded and folded[-1] == " ":
        folded.pop()
        mapping.pop()
    return "".join(folded), mapping


def _words(folded: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", folded or "")]


def _expand_to_sentences(text: str, start: int, end: int) -> tuple[int, int]:
    while start > 0 and text[start - 1] not in ".!?":
        start -= 1
    while start < end and text[start].isspace():
        start += 1
    while end < len(text) and (end == 0 or text[end - 1] not in ".!?"):
        end += 1
    return start, end


def snap_verbatim_quote_to_transcript(quote: str | None, transcript: str | None) -> str:
    """Return the exact transcript slice the quote refers to.

    The model often paraphrases `verbatim_quote`. Reports must show the same
    words as the conversation, so replace the paraphrase with the covering
    span of matching words copied from the transcript.
    """
    quote_text = (quote or "").strip()
    source = transcript or ""
    if not quote_text or not source:
        return quote_text

    quote_fold, _ = _fold(quote_text)
    source_fold, source_map = _fold(source)
    if not quote_fold or not source_fold:
        return quote_text

    exact_at = source_fold.find(quote_fold)
    if exact_at >= 0:
        start = source_map[exact_at]
        end = source_map[exact_at + len(quote_fold) - 1] + 1
        start, end = _expand_to_sentences(source, start, end)
        return _SPEAKER_LABEL_RE.sub("", source[start:end]).strip()

    needle = [word for word in quote_fold.split(" ") if word]
    hay = _words(source_fold)
    if not needle or not hay:
        return quote_text

    min_run = len(needle) if len(needle) <= 2 else 3
    hay_from = 0
    needle_from = 0
    matched: list[tuple[int, int]] = []
    while needle_from < len(needle):
        best_count = 0
        best_at = -1
        for hay_index in range(hay_from, len(hay)):
            count = 0
            while (
                hay_index + count < len(hay)
                and needle_from + count < len(needle)
                and hay[hay_index + count][0] == needle[needle_from + count]
            ):
                count += 1
            if count > best_count:
                best_count = count
                best_at = hay_index
                if count == len(needle) - needle_from:
                    break
        if best_count >= min_run and best_at >= 0:
            matched.append((best_at, best_at + best_count))
            hay_from = best_at + best_count
            needle_from += best_count
            continue
        needle_from += 1

    if not matched:
        return quote_text

    first = hay[matched[0][0]]
    last = hay[matched[-1][1] - 1]
    start = source_map[first[1]]
    end = source_map[last[2] - 1] + 1
    start, end = _expand_to_sentences(source, start, end)
    snapped = _SPEAKER_LABEL_RE.sub("", source[start:end]).strip()
    return snapped or quote_text
