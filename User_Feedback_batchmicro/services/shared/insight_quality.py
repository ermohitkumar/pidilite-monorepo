"""Drop usage-only / catch-all / cloned insights after Gemini tagging.

Phase 1 used to extract every SKU mention. Those rows then landed on
tag 6 (Performance improvements) because no usage tag exists. These
filters enforce: real feedback, tag-justified summary, one story → one row.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

# Stable taxonomy ids from scripts/data/feedback_taxonomy.json
TAG_PACKAGING_COMPLAINT = 5
TAG_PERFORMANCE_IMPROVEMENTS = 6
TAG_SITE_VISITS = 17

_FEEDBACK_RE = re.compile(
    r"\b("
    r"leak|leaking|bubble|smell|dry(?:ing|s)?|coverage|bond|grip|strength|"
    r"shelf(?:\s+life)?|pot\s+life|longevity|adhesion|quality|complaint|"
    r"better|worse|improv|trouble|problem|issue|expensive|cheap|"
    r"scheme|points?|credit|stock|margin|meet|carnival|redemption|gift|trip|"
    r"kyc|bonus|loyalty|competitor|compared|than|packag|token|scan|"
    r"not\s+coming|delayed|late|app|functionality|redempt|"
    r"easy|sets?|sticking|grab|applicator|not\s+sent|fragrance|ineffective|termite|"
    r"good|better|excellent|superb|liked|like"
    r")\b",
    re.IGNORECASE,
)
_USAGE_RE = re.compile(
    r"\b(used|using|uses|ordered|order|applied|apply|kg|introduced|asking|asked)\b",
    re.IGNORECASE,
)
_FME_PITCH_RE = re.compile(
    r"\b(the\s+fme|fme)\b.+\b(introduced|is asking|asks|demonstrat|explain)",
    re.IGNORECASE,
)
_FME_ATTRIB_RE = re.compile(
    r"^\s*(the\s+)?fme\b|"
    r"\bthe fme (explained|clarified|informs|informed|introduced|asks|asked|is asking|noted|reminds)\b",
    re.IGNORECASE,
)
_SPEAKER_LABEL_RE = re.compile(
    r"\b(FME|Speaker\s*1)\s*:",
    re.IGNORECASE,
)
_PERF_RE = re.compile(
    r"\b("
    r"improv|strength|shelf(?:\s+life)?|pot\s+life|longevity|coverage|"
    r"bond|grip|dry(?:ing|s)?|adhesion|performance|quality|trouble|"
    r"better|worse|new\s+application|easy|sets?|sticking|grab|"
    r"good|excellent|superb|liked"
    r")\b",
    re.IGNORECASE,
)
_PACK_RE = re.compile(
    r"\b("
    r"leak|leaking|packag|token|bubble|smell|adhesion|"
    r"masking|uneven|rubbery|hard.to.open|lid|tin|cap|applicator|not\s+sent"
    r")\b",
    re.IGNORECASE,
)


def _blob(item: dict) -> str:
    return f"{item.get('summary') or ''} {item.get('verbatim_quote') or ''}"


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _tag_ids(item: dict) -> set[int]:
    out: set[int] = set()
    for raw in item.get("tag_ids") or []:
        try:
            out.add(int(raw))
        except (TypeError, ValueError):
            continue
    return out


def is_user_feedback(item: dict) -> bool:
    """Feedback must be the User's answer — never an FME pitch or FME-only quote."""
    quote = (item.get("verbatim_quote") or "").strip()
    summary = (item.get("summary") or "").strip()
    if not quote:
        return False
    if _SPEAKER_LABEL_RE.search(quote):
        return False
    if _FME_ATTRIB_RE.search(summary) and not re.search(
        r"\b(user|customer|dealer|contractor)\b", summary, re.IGNORECASE
    ):
        return False
    if _FME_PITCH_RE.search(_blob(item)) and not _FEEDBACK_RE.search(quote):
        return False
    return True


def is_actionable_feedback(item: dict) -> bool:
    """True when the User stated a complaint, comparison, request, or quality claim."""
    if not is_user_feedback(item):
        return False
    text = _blob(item)
    if _FEEDBACK_RE.search(text):
        return True
    if _USAGE_RE.search(text):
        return False
    return False


def tag_justifies_text(item: dict) -> bool:
    """Catch-all tags must match the tag description, not mere usage."""
    tags = _tag_ids(item)
    text = _blob(item)
    if TAG_PERFORMANCE_IMPROVEMENTS in tags and not _PERF_RE.search(text):
        return False
    if TAG_PACKAGING_COMPLAINT in tags and not _PACK_RE.search(text):
        return False
    if TAG_SITE_VISITS in tags and not re.search(
        r"\b(visit|came|coming|late|schedul|fme)\b", text, re.IGNORECASE
    ):
        return False
    return True


def _keep_clone_index(insights: list[dict], idxs: list[int]) -> int:
    summary = (insights[idxs[0]].get("summary") or "").lower()
    keep = idxs[0]
    best_pos = 10**9
    for idx in idxs:
        pname = (insights[idx].get("product_name") or "").strip().lower()
        if not pname:
            continue
        pos = summary.find(pname)
        if 0 <= pos < best_pos:
            keep = idx
            best_pos = pos
    return keep


def dedupe_cloned_insights(insights: list[dict]) -> list[dict]:
    """Keep one row when the same summary/quote was cloned onto several SKUs."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, item in enumerate(insights):
        groups[(_norm(item.get("summary")), _norm(item.get("verbatim_quote")))].append(idx)

    drop: set[int] = set()
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        keep = _keep_clone_index(insights, idxs)
        for idx in idxs:
            if idx == keep:
                continue
            drop.add(idx)
            logger.info(
                "Dropping cloned insight product=%r summary=%r",
                insights[idx].get("product_name"),
                (insights[idx].get("summary") or "")[:80],
            )
    return [item for idx, item in enumerate(insights) if idx not in drop]


def filter_meaningful_insights(insights: list[dict]) -> list[dict]:
    """Omit usage-only rows, unjustified catch-all tags, and SKU clones."""
    kept: list[dict] = []
    for item in insights:
        if not isinstance(item, dict):
            continue
        if not item.get("tag_ids"):
            continue
        if not is_user_feedback(item):
            logger.info(
                "Dropping FME-only insight product=%r summary=%r",
                item.get("product_name"),
                (item.get("summary") or "")[:80],
            )
            continue
        if not is_actionable_feedback(item):
            logger.info(
                "Dropping usage-only insight product=%r summary=%r",
                item.get("product_name"),
                (item.get("summary") or "")[:80],
            )
            continue
        if not tag_justifies_text(item):
            logger.info(
                "Dropping tag-mismatch insight tags=%s summary=%r",
                item.get("tag_ids"),
                (item.get("summary") or "")[:80],
            )
            continue
        kept.append(item)
    return dedupe_cloned_insights(kept)
