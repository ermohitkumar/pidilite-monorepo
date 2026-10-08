"""Compact insight lines, token estimates, and adaptive chunk packing."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import date
from typing import Any, Optional

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from services.period_summarize.period_keys import (
    INSIGHT_GRAINS,
    display_key,
    group_label,
    group_token,
    parse_insight_key,
)

INPUT_BUDGET_TOKENS = 8000
COMBINE_BUDGET_TOKENS = 6000
FLOOR_LINES = 15
LINE_SUMMARY_CHARS = 160
CHILD_SUMMARY_TOKENS = 400
MAX_PACK_DEPTH = 20
INSIGHT_CALL_COLUMNS = ("fd.call_date", "fb.created_at")


def estimate_tokens(text_value: str | None) -> int:
    if not text_value:
        return 0
    return max(1, math.ceil(len(text_value) / 4))


def truncate_chars(value: str | None, limit: int) -> str:
    text_value = (value or "").replace("\n", " ").strip()
    if len(text_value) <= limit:
        return text_value
    return text_value[: max(0, limit - 1)] + "…"


def truncate_to_tokens(value: str | None, max_tokens: int = CHILD_SUMMARY_TOKENS) -> str:
    text_value = (value or "").strip()
    max_chars = max_tokens * 4
    if len(text_value) <= max_chars:
        return text_value
    return text_value[: max(0, max_chars - 1)] + "…"


def compact_line(row: dict[str, Any]) -> str:
    call_date = row.get("call_date")
    if hasattr(call_date, "isoformat"):
        day = call_date.isoformat()[:10]
    else:
        day = str(call_date or "")[:10]
    group = str(row.get("group_type") or "").replace(" GROUP", "")[:12]
    product = truncate_chars(str(row.get("product_name") or "-"), 40)
    tags = truncate_chars(str(row.get("tags") or ""), 40)
    sentiment = row_sentiment(row) or "-"
    summary = truncate_chars(str(row.get("ai_summary") or ""), LINE_SUMMARY_CHARS)
    return f"{day}|{group}|{product}|{tags}|{sentiment}|{summary}"


def normalize_sentiment(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"positive", "pos"}:
        return "Positive"
    if raw in {"negative", "neg"}:
        return "Negative"
    if raw in {"neutral", "neu"}:
        return "Neutral"
    return None


_POS_PHRASES = (
    "never had trouble",
    "prevents bubbling",
    "prevent bubbling",
    "no chemical smell",
    "no adverse",
    "makes work easy",
    "work easier",
    "very good",
    "immensely impressed",
)
_NEG_PHRASES = (
    "less than desired",
    "not scanning",
    "too long",
    "too slow",
    "should be faster",
    "poor adhesion",
    "push other brands",
    "does not exist",
    "not working",
)
_POS_WORDS = re.compile(
    r"\b(good|great|excellent|prais(?:e|es|ed)|happy|better|best|impressed|"
    r"satisfaction|satisfied|appreciate[sd]?|likes?|easier|easy|strong|"
    r"effective|beneficial|necessity|versatility|recommend(?:s|ed|ations)?)\b",
    re.I,
)
_NEG_WORDS = re.compile(
    r"\b(poor|lacks?|missing|stopped|leak(?:s|age|ed)?|delay|complaint|issue|"
    r"problem|defect|weak|fail(?:ed|ure)?|bad|trouble|bubbling|inconvenien(?:ce|cing)|"
    r"doesn(?:'|’)t fully|not scanning|less than)\b",
    re.I,
)
_FACTUAL = re.compile(
    r"\b(asking|asks?|confirm(?:s|ed|ing)?|understands|clarification|"
    r"checks the app|posts videos|wants to redeem|has not yet|"
    r"does not regularly|has \d+ points|states that the current)\b",
    re.I,
)


def infer_sentiment(value: Any) -> str:
    """Positive / Neutral / Negative from insight text when the model did not store a label."""
    stored = normalize_sentiment(value)
    if stored:
        return stored
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return "Neutral"
    lowered = text.lower()
    pos = sum(1 for phrase in _POS_PHRASES if phrase in lowered)
    neg = sum(1 for phrase in _NEG_PHRASES if phrase in lowered)
    cleaned = lowered
    for phrase in _POS_PHRASES + _NEG_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    pos += len(_POS_WORDS.findall(cleaned))
    neg += len(_NEG_WORDS.findall(cleaned))
    if neg > pos:
        return "Negative"
    if pos > neg:
        return "Positive"
    if _FACTUAL.search(text) or pos == 0:
        return "Neutral"
    return "Neutral"


def row_sentiment(row: dict[str, Any]) -> str:
    stored = normalize_sentiment(row.get("sentiment") or row.get("sentiment_label"))
    if stored:
        return stored
    return infer_sentiment(f"{row.get('ai_summary') or ''} {row.get('verbatim_quote') or ''}")


def _majority_label(labels: list[str]) -> str | None:
    counts = Counter(label for label in labels if label)
    if not counts:
        return None
    order = {"Negative": 0, "Neutral": 1, "Positive": 2}
    ranked = sorted(
        counts.items(),
        key=lambda item: (-item[1], order.get(item[0], 9)),
    )
    return ranked[0][0]


def _user_key(row: dict[str, Any]) -> str:
    for key in ("user_id", "membership_no", "job_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _short_finding(row: dict[str, Any]) -> str:
    text = str(row.get("ai_summary") or "").strip()
    if not text:
        return ""
    return re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip().rstrip(".")


def _region_label(row: dict[str, Any]) -> str:
    for key in ("rfmm_key", "zone_key", "bde_key"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _quote_text(row: dict[str, Any]) -> str:
    quote = str(row.get("verbatim_quote") or row.get("ai_summary") or "").strip()
    quote = " ".join(quote.split())
    if not quote:
        return ""
    region = _region_label(row)
    if region and not quote.upper().endswith(region.upper()):
        return f"{quote} — {region}"
    return quote


_THEME_RULES = (
    (re.compile(r"\bbubbl", re.I), "bubbling issues"),
    (re.compile(r"\bleak|\blid\b|\bcap leak|\btin leak|\bpackag", re.I), "leakage / packaging"),
    (
        re.compile(
            r"less setting|too long to set|longer setting|setting time|sets? in\b|drying time|fast drying|"
            r"quicker setting|should be faster|sticks in\s+\d",
            re.I,
        ),
        "setting time",
    ),
    (re.compile(r"quick(?:er)? application|fast application|application speed", re.I), "application speed"),
    (re.compile(r"\bbend(?:ing|s)?\b|\bwarp(?:ing|s|ed)?\b", re.I), "bending / warping"),
    (
        re.compile(
            r"\badhesion|\bgrip\b|\bstick(?:ing|s)?\b|\bbond(?:ing)?\b|\bstrength\b|\bstrong\b",
            re.I,
        ),
        "grip / adhesion",
    ),
    (re.compile(r"\bsmell|\bodou?r|\bneutral", re.I), "smell"),
    (re.compile(r"\bpoints?\b|\bloyalty|\bredemption|\bquiz", re.I), "loyalty / points"),
    (re.compile(r"\bapp\b|\bdashboard|\bquotation", re.I), "app experience"),
    (re.compile(r"\bopen time|\bgrab\b", re.I), "open time / grab"),
    (re.compile(r"edge[- ]?band(?:ing)?", re.I), "edge banding"),
    (re.compile(r"never had trouble|no trouble|\breliab", re.I), "reliability"),
    (
        re.compile(
            r"\bquality\b|\bgood product\b|\bvery good\b|\bprais|\bexcellent\b|"
            r"\bholding well\b|\bgood to use\b|\bis good\b|\bare good\b",
            re.I,
        ),
        "product quality",
    ),
    (re.compile(r"prefers?|better than|better for", re.I), "product preference"),
)
_PRAISE_THEME_RE = re.compile(
    r"^(?:a |the |very )?(?:good|great|excellent|nice|ok|okay)(?: product)?$"
    r"|^(?:product )?quality$"
    r"|^(?:overall )?performance$"
    r"|^(?:user )?prais",
    re.I,
)
_VAGUE_THEMES = {
    "performance improvements",
    "existing product",
    "existing product - performance improvements",
    "quality",
    "packaging",
    "user scheme",
    "functionality",
    "information",
    "other feedback",
    "feedback",
}
_USER_PREFIX_RE = re.compile(
    r"^(?:noted:\s*)?(?:the\s+)?users?\s+"
    r"(?:praises|states?|suggests|experienced|has never had trouble with|"
    r"has|have|likes?|appreciates|mentions|reports?|said|says|finds?|found|"
    r"prefers?|is happy with|does not|doesn't|do not)\s+",
    re.I,
)
_PRODUCT_HINTS = (
    "Fevicol Nail Free",
    "Fevicol RELAM",
    "Fevicol Marine",
    "Fevicol MARINE",
    "Fevicol SH",
    "Fevicol Multilock",
    "Fevicol HEATX",
    "Jeevan Jyoti",
    "Ezee Spray",
)


def _is_vague_theme(label: str) -> bool:
    text = re.sub(r"\s+", " ", str(label or "")).strip().lower().rstrip(".")
    return not text or text in _VAGUE_THEMES or text.startswith("existing product")


def _canonicalize_theme(theme: str) -> str:
    """Map free-form / near-duplicate labels onto one bucket so similar praise collapses."""
    text = re.sub(r"\s+", " ", str(theme or "")).strip().rstrip(".")
    if not text:
        return "product quality"
    for pattern, label in _THEME_RULES:
        if pattern.search(text):
            return label
    if _PRAISE_THEME_RE.search(text) or _is_vague_theme(text):
        return "product quality"
    return text


def _tag_theme(row: dict[str, Any]) -> str:
    tags = [part.strip() for part in str(row.get("tags") or "").split(",") if part.strip()]
    raw = tags[0] if tags else ""
    if " - " in raw:
        raw = raw.rsplit(" - ", 1)[-1].strip()
    return raw


def _strip_product_mentions(text: str, product: str = "") -> str:
    cleaned = str(text or "")
    names = [product, *_PRODUCT_HINTS]
    for name in sorted({item for item in names if item}, key=len, reverse=True):
        cleaned = re.sub(re.escape(name), " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\bFevicol\b", " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip(" -–,.'\"")


def _cleaned_phrase(text: str, product: str = "", limit: int = 40) -> str:
    cleaned = _USER_PREFIX_RE.sub("", str(text or "").strip())
    cleaned = re.split(r"\bThey also\b", cleaned, maxsplit=1, flags=re.I)[0]
    cleaned = re.split(r"[.!?;]", cleaned, maxsplit=1)[0]
    aside = re.search(r",\s*(?:highlighting|noting)\b", cleaned, flags=re.I)
    if aside and len(cleaned[: aside.start()].split()) >= 6:
        cleaned = cleaned[: aside.start()]
    cleaned = _strip_product_mentions(cleaned, product)
    # Product removal can leave broken "quality of is good" fragments.
    cleaned = re.sub(r"\bof\s+(?=is\b|has\b|was\b|are\b|were\b)", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^['’]?s\s+", "", cleaned)
    for _ in range(3):
        nxt = re.sub(
            r"^(?:for its|for|that|to be|to|is|has|have|found|and|noting|highlighting(?: its)?|its)\s+",
            "",
            cleaned,
            flags=re.I,
        )
        if nxt == cleaned:
            break
        cleaned = nxt
    cleaned = re.sub(r"\bthan\s+for\b", "than the other product for", cleaned, flags=re.I)
    cleaned = re.sub(r"\bwhile\s+has\b", "while the other product has", cleaned, flags=re.I)
    if re.match(r"^over\b", cleaned, flags=re.I):
        cleaned = f"prefers it {cleaned}"
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–,").rstrip(".")
    words = cleaned.split()
    if limit > 0 and len(words) > limit:
        cleaned = " ".join(words[:limit])
    return cleaned


def _keyword_pattern(theme: str):
    for pattern, label in _THEME_RULES:
        if label == theme:
            return pattern
    return None


def _theme_labels(row: dict[str, Any]) -> list[str]:
    blob = str(row.get("ai_summary") or "").strip() or str(row.get("verbatim_quote") or "").strip()
    hits = [_canonicalize_theme(label) for pattern, label in _THEME_RULES if pattern.search(blob)]
    unique: list[str] = []
    for label in hits:
        if label not in unique:
            unique.append(label)
    if unique:
        # Prefer a concrete issue theme over generic praise when both fire.
        if "product quality" in unique and len(unique) > 1:
            unique = [item for item in unique if item != "product quality"]
        if "product preference" in unique and len(unique) > 1:
            unique = [item for item in unique if item != "product preference"]
        return unique[:1]
    phrase = _cleaned_phrase(_short_finding(row), str(row.get("product_name") or ""))
    if phrase and not _is_vague_theme(phrase):
        return [_canonicalize_theme(phrase)]
    return []


def _observation_detail(text: str, product: str = "") -> str:
    return _cleaned_phrase(text, product, limit=48)


def _compact_details(summaries: list[str], product: str, theme: str) -> str:
    snippets: list[str] = []
    seen: set[str] = set()
    theme_key = re.sub(r"\s+", " ", theme.lower()).strip()
    pattern = _keyword_pattern(theme)
    ranked = sorted((str(item or "").strip() for item in summaries if str(item or "").strip()), key=len, reverse=True)
    for item in ranked:
        if pattern and not pattern.search(item):
            continue
        detail = _observation_detail(item, product)
        key = detail.lower()
        if not detail or key in seen:
            continue
        if key == theme_key or theme_key.startswith(key):
            continue
        # Drop mid-phrase fragments left after product-name stripping.
        if re.search(r"\b(of|the|a|an|and|or|to|for|with|is|are|was|were|has|have|instead)$", detail, flags=re.I):
            continue
        if re.search(r"\bof\s+(?:is|has|was|are)\b", detail, flags=re.I):
            continue
        seen.add(key)
        snippets.append(detail)
        if len(snippets) == 2:
            break
    return "; ".join(snippets)


def _soft_theme(label: str) -> str:
    text = re.sub(r"\s+", " ", str(label or "")).strip().rstrip(".")
    if text and text[0].isupper() and not text.isupper() and len(text) > 1:
        return text[0].lower() + text[1:]
    return text


def _point_line(theme: str, count: int, index: int, detail: str = "") -> str:
    theme = _soft_theme(theme) or "this feedback"
    if theme:
        theme = theme[0].upper() + theme[1:]
    detail = re.sub(r"\s+", " ", str(detail or "")).strip(" -–.")
    count = max(int(count or 0), 1)
    noun = "user" if count == 1 else "users"
    tail = f"({count} {noun})"
    if detail and detail.lower() not in theme.lower():
        return f"{theme} — {detail} {tail}"
    return f"{theme} {tail}"


def _resolve_product(row: dict[str, Any], known_products: list[str]) -> str:
    name = str(row.get("product_name") or "").strip()
    if name:
        return name
    blob = f"{row.get('ai_summary') or ''} {row.get('verbatim_quote') or ''}".lower()
    for product in known_products:
        if product.lower() in blob:
            return product
    for hint in _PRODUCT_HINTS:
        if hint.lower() in blob:
            return hint
    return ""


def findings_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known_products = sorted(
        {str(row.get("product_name") or "").strip() for row in rows if str(row.get("product_name") or "").strip()},
        key=len,
        reverse=True,
    )
    tree: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        product = _resolve_product(row, known_products)
        themes = _theme_labels(row)
        if not themes:
            detail = _observation_detail(str(row.get("ai_summary") or ""), product)
            if detail:
                themes = [detail]
        summary = str(row.get("ai_summary") or "").strip()
        for theme in themes:
            if _is_vague_theme(theme):
                continue
            bucket = _canonicalize_theme(theme)
            if _is_vague_theme(bucket):
                continue
            group = tree.setdefault(product, {}).setdefault(
                bucket.lower(),
                {"theme": bucket, "users": set(), "summaries": [], "sentiments": []},
            )
            group["users"].add(_user_key(row) or str(row.get("job_id") or "") or f"row:{id(row)}")
            group["sentiments"].append(row_sentiment(row))
            if summary:
                group["summaries"].append(summary)
    findings: list[dict[str, Any]] = []
    for product, themes in tree.items():
        points: list[dict[str, Any]] = []
        product_users: set[str] = set()
        product_sentiments: list[str] = []
        ranked = sorted(
            themes.items(),
            key=lambda item: (-len(item[1]["users"]), item[0].lower()),
        )
        for index, (_theme_key, group) in enumerate(ranked):
            users = {item for item in group["users"] if item}
            count = len(users)
            if count < 1:
                continue
            product_users.update(users)
            product_sentiments.extend(str(item) for item in group.get("sentiments") or [])
            narratives: list[str] = []
            seen: set[str] = set()
            for item in group["summaries"]:
                key = " ".join(str(item).split()).lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                narratives.append(str(item).strip())
            theme_label = str(group.get("theme") or _theme_key)
            detail = _compact_details(narratives, product, theme_label)
            points.append({
                "theme": theme_label,
                "user_count": count,
                "summary": " ".join(narratives),
                "detail": detail,
                "line": _point_line(theme_label, count, index, detail),
                "sentiment": _majority_label(list(group.get("sentiments") or [])),
            })
        if not points:
            continue
        findings.append({
            "title": product,
            "product": product,
            "points": points,
            "user_count": len(product_users),
            "sentiment": _majority_label(product_sentiments),
        })
    findings.sort(key=lambda item: (-int(item["user_count"]), str(item["title"])))
    return findings[:12]


def format_findings(findings: list[dict[str, Any]] | None) -> str:
    blocks: list[str] = []
    for item in findings or []:
        title = str(item.get("product") or item.get("title") or "").strip()
        show_title = bool(title) and title.lower() not in {"other", "unknown"}
        points = item.get("points") or []
        lines: list[str] = [title] if show_title else []
        if points:
            for point in points:
                line = str(point.get("line") or "").strip()
                if not line:
                    theme = str(point.get("theme") or point.get("summary") or "").strip()
                    line = _point_line(
                        theme,
                        int(point.get("user_count") or 0),
                        len(lines),
                        str(point.get("detail") or ""),
                    )
                lines.append(f"• {line}")
        elif str(item.get("summary") or item.get("data") or "").strip():
            lines.append(f"• {item.get('summary') or item.get('data')}")
        if len(lines) > (1 if show_title else 0):
            blocks.append("\n".join(lines).strip())
    return "\n\n".join(blocks)


def merge_findings(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_product: dict[str, dict[str, Any]] = {}
    for child in children:
        extra = child.get("highlights") or {}
        for item in extra.get("findings") or []:
            if not isinstance(item, dict):
                continue
            product = str(item.get("product") or "").strip()
            title = str(item.get("title") or "").strip()
            if not product and " — " in title:
                _left, right = title.split(" — ", 1)
                product = right.rstrip(".")
            elif not product and title.lower() not in {"other", "unknown"}:
                product = title
            current = by_product.setdefault(
                product.lower(),
                {"title": product, "product": product, "points": {}, "user_count": 0, "sentiments": []},
            )
            current["user_count"] += int(item.get("user_count") or 0)
            if item.get("sentiment"):
                current["sentiments"].append(str(item["sentiment"]))
            incoming = item.get("points") or []
            if not incoming and (item.get("summary") or item.get("theme")):
                incoming = [{
                    "theme": item.get("theme") or item.get("title") or "feedback",
                    "user_count": item.get("user_count") or 0,
                    "summary": item.get("summary") or "",
                    "detail": item.get("detail") or "",
                    "line": item.get("line") or "",
                }]
            for point in incoming:
                if not isinstance(point, dict):
                    continue
                theme = str(point.get("theme") or "").strip() or "feedback"
                if _is_vague_theme(theme) and (point.get("detail") or point.get("summary")):
                    theme = str(point.get("detail") or _cleaned_phrase(str(point.get("summary") or ""))) or theme
                theme = _canonicalize_theme(theme)
                bucket = current["points"].setdefault(
                    theme.lower(),
                    {"theme": theme, "user_count": 0, "summary": "", "detail": "", "line": "", "sentiments": []},
                )
                bucket["user_count"] += int(point.get("user_count") or 0)
                if point.get("sentiment"):
                    bucket["sentiments"].append(str(point["sentiment"]))
                if point.get("summary") and point["summary"] not in bucket["summary"]:
                    bucket["summary"] = f"{bucket['summary']} {point['summary']}".strip()
                if point.get("detail") and point["detail"] not in bucket["detail"]:
                    bucket["detail"] = f"{bucket['detail']}; {point['detail']}".strip("; ")
                if point.get("line"):
                    bucket["line"] = str(point["line"])
    findings: list[dict[str, Any]] = []
    for item in by_product.values():
        points = sorted(item["points"].values(), key=lambda point: (-int(point["user_count"]), point["theme"]))
        for index, point in enumerate(points):
            detail = str(point.get("detail") or "") or _compact_details(
                [point.get("summary") or ""],
                item["product"],
                point["theme"],
            )
            point["detail"] = detail
            point["line"] = _point_line(point["theme"], int(point["user_count"] or 0), index, detail)
            point["sentiment"] = _majority_label(list(point.get("sentiments") or []))
            point.pop("sentiments", None)
        findings.append({
            "title": item["title"],
            "product": item["product"],
            "points": points,
            "user_count": item["user_count"],
            "sentiment": _majority_label(list(item.get("sentiments") or [])),
        })
    findings.sort(key=lambda item: (-int(item["user_count"]), str(item["title"])))
    return findings[:12]


def _topic_labels(row: dict[str, Any]) -> list[str]:
    finding = _short_finding(row)
    if finding:
        return [finding]
    labels: list[str] = []
    for part in str(row.get("tags") or "").split(","):
        tag = part.strip()
        if tag and tag not in labels:
            labels.append(tag)
    product = str(row.get("product_name") or "").strip()
    if product and product not in labels:
        labels.append(product)
    return labels


def topic_sentence(count: int, label: str) -> str:
    clean = str(label or "").strip().rstrip(".")
    if clean:
        clean = clean[0].upper() + clean[1:]
    noun = "user" if int(count) == 1 else "users"
    return f"{clean} ({int(count)} {noun})."


def topic_sentences(topics: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for item in topics or []:
        label = str(item.get("label") or "").strip()
        count = int(item.get("user_count") or 0)
        if not label or count < 1:
            continue
        parts.append(topic_sentence(count, label))
    return " ".join(parts)


def rollup_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    job_ids = {str(row.get("job_id") or "").strip() for row in rows}
    job_ids.discard("")
    users = {_user_key(row) for row in rows}
    users.discard("")
    issue_users = {
        _user_key(row)
        for row in rows
        if row_sentiment(row) == "Negative"
    }
    issue_users.discard("")
    sentiments = [row_sentiment(row) for row in rows]
    sentiment_counts = Counter(item for item in sentiments if item)
    sentiment = _majority_label(sentiments)
    topic_users: dict[str, set[str]] = {}
    for row in rows:
        user = _user_key(row)
        for label in _topic_labels(row):
            topic_users.setdefault(label, set()).add(user or str(row.get("job_id") or ""))
    topics = [
        {"label": label, "user_count": len(users_for)}
        for label, users_for in topic_users.items()
        if label
    ]
    topics.sort(key=lambda item: (-int(item["user_count"]), str(item["label"])))
    findings = findings_from_rows(rows)
    site_visits = len(job_ids) or len({str(row.get("call_date") or "")[:10] for row in rows if row.get("call_date")})
    return {
        "call_count": site_visits,
        "site_visit_count": site_visits,
        "user_count": len(users),
        "user_issue_count": len(issue_users),
        "insight_count": len(rows),
        "sentiment": sentiment,
        "sentiment_counts": dict(sentiment_counts),
        "topics": topics[:20],
        "findings": findings,
    }


def combine_child_rollups(children: list[dict[str, Any]]) -> dict[str, Any]:
    site_visits = 0
    user_count = 0
    user_issue_count = 0
    insight_count = 0
    sentiment_counts: Counter[str] = Counter()
    topic_counts: dict[str, int] = {}
    for child in children:
        extra = child.get("highlights") or {}
        site_visits += int(
            extra.get("site_visit_count")
            or child.get("call_count")
            or extra.get("call_count")
            or 0
        )
        user_count += int(extra.get("user_count") or 0)
        user_issue_count += int(extra.get("user_issue_count") or 0)
        insight_count += int(child.get("insight_count") or extra.get("insight_count") or 0)
        counts = extra.get("sentiment_counts") or {}
        if isinstance(counts, dict) and counts:
            sentiment_counts.update({str(key): int(value or 0) for key, value in counts.items()})
        else:
            label = normalize_sentiment(extra.get("sentiment"))
            if label:
                sentiment_counts[label] += 1
        for topic in extra.get("topics") or []:
            if not isinstance(topic, dict):
                continue
            label = str(topic.get("label") or "").strip()
            if not label:
                continue
            topic_counts[label] = topic_counts.get(label, 0) + int(topic.get("user_count") or 0)
    sentiment = _majority_label(list(sentiment_counts.elements())) if sentiment_counts else None
    topics = [
        {"label": label, "user_count": count}
        for label, count in topic_counts.items()
    ]
    topics.sort(key=lambda item: (-int(item["user_count"]), str(item["label"])))
    return {
        "call_count": site_visits,
        "site_visit_count": site_visits,
        "user_count": user_count,
        "user_issue_count": user_issue_count,
        "insight_count": insight_count,
        "sentiment": sentiment,
        "sentiment_counts": dict(sentiment_counts),
        "topics": topics[:20],
        "findings": merge_findings(children),
    }


def _summary_key(line: str) -> str:
    summary = line.rsplit("|", 1)[-1].strip().lower()
    return "".join(summary.split())


def dedup_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = _summary_key(line)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def source_hash(lines: list[str]) -> str:
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sample_leaders(lines: list[str], floor: int = FLOOR_LINES) -> list[str]:
    products: list[str] = []
    for line in lines:
        parts = line.split("|")
        products.append(parts[2].strip() if len(parts) > 2 else "")
    common = {name for name, _count in Counter(products).most_common(5) if name and name != "-"}
    leaders = [line for line in lines if len(line.split("|")) > 2 and line.split("|")[2].strip() in common]
    rest = [line for line in lines if line not in leaders]
    selected = (leaders + rest)[:floor]
    return selected


def pack_chunks(
    lines: list[str],
    budget: int = INPUT_BUDGET_TOKENS,
    floor: int = FLOOR_LINES,
) -> tuple[list[list[str]], bool]:
    """Split lines so each chunk is under the token budget. Never send oversized prompts."""
    truncated = False

    def _split(items: list[str], depth: int = 0) -> list[list[str]]:
        nonlocal truncated
        if not items:
            return []
        packed = "\n".join(items)
        if estimate_tokens(packed) <= budget:
            return [items]
        if len(items) <= floor or depth >= MAX_PACK_DEPTH:
            truncated = True
            sampled = sample_leaders(items, floor)
            if estimate_tokens("\n".join(sampled)) > budget:
                # Last resort: keep shrinking until it fits or a single truncated line remains.
                while len(sampled) > 1 and estimate_tokens("\n".join(sampled)) > budget:
                    sampled = sampled[: max(1, len(sampled) // 2)]
                if sampled and estimate_tokens(sampled[0]) > budget:
                    sampled = [truncate_to_tokens(sampled[0], budget)]
            return [sampled]
        mid = max(1, len(items) // 2)
        return _split(items[:mid], depth + 1) + _split(items[mid:], depth + 1)

    return _split(lines), truncated


def child_source_lines(children: list[dict[str, Any]], budget: int = COMBINE_BUDGET_TOKENS) -> tuple[list[str], bool]:
    lines = []
    for child in children:
        key = child.get("grain_label") or display_key(child.get("grain_key")) or child.get("grain_key") or ""
        text_value = truncate_to_tokens(child.get("summary_text") or "", CHILD_SUMMARY_TOKENS)
        lines.append(f"{key}: {text_value}")
    chunks, truncated = pack_chunks(lines, budget=budget)
    flat: list[str] = []
    for chunk in chunks:
        flat.extend(chunk)
    if len(chunks) <= 1:
        return flat, truncated
    return lines, truncated


def _dialect_name(db: Session) -> str:
    bind = db.get_bind()
    return getattr(getattr(bind, "dialect", None), "name", "") or "postgresql"


def call_date_sql(dialect: str, *columns: str) -> str:
    """Date filter that tolerates mixed timestamptz / varchar columns."""
    if dialect == "sqlite":
        if len(columns) == 1:
            return f"DATE({columns[0]})"
        return f"DATE(COALESCE({', '.join(columns)}))"
    arms = [f"CAST({column} AS DATE)" for column in columns]
    if len(arms) == 1:
        return arms[0]
    return f"COALESCE({', '.join(arms)})"


def _group_filter(group_type: Optional[str]) -> tuple[str, dict[str, Any]]:
    token = group_token(group_type)
    label = group_label(token)
    if not label:
        return "", {}
    return " AND UPPER(TRIM(COALESCE(fb.group_type, ''))) = :group_type", {"group_type": label.upper()}


def _table_columns(db: Session, table: str) -> set[str]:
    bind = db.get_bind()
    try:
        return {column["name"] for column in inspect(bind).get_columns(table)}
    except Exception:
        return set()


def _user_id_sql(db: Session) -> str:
    cols = _table_columns(db, "file_details")
    parts: list[str] = []
    for name in ("user_id_metadata", "membership_no", "user_id", "site_number"):
        if name in cols:
            parts.append(f"NULLIF(TRIM(COALESCE(fd.{name}, '')), '')")
    dialect = _dialect_name(db)
    job_cast = "CAST(fb.job_id AS TEXT)" if dialect != "sqlite" else "CAST(fb.job_id AS TEXT)"
    parts.append(job_cast)
    return f"COALESCE({', '.join(parts)})"


def _sentiment_sql(db: Session) -> str:
    cols = _table_columns(db, "feedbacks")
    if "sentiment_label" in cols:
        return "fb.sentiment_label"
    return "NULL"


def _verbatim_sql(db: Session) -> str:
    cols = _table_columns(db, "feedbacks")
    if "verbatim_quote" in cols:
        return "COALESCE(fb.verbatim_quote, '')"
    return "''"


def _insight_select_sql(db: Session, extra_where: str = "") -> tuple[Any, str]:
    dialect = _dialect_name(db)
    call_date = call_date_sql(dialect, *INSIGHT_CALL_COLUMNS)
    tag_agg = "GROUP_CONCAT(ft.tag_name, ',')" if dialect == "sqlite" else "string_agg(ft.tag_name, ',')"
    sql = text(
        f"""
        SELECT
            {call_date} AS call_date,
            fb.id AS insight_id,
            fb.job_id AS job_id,
            {_user_id_sql(db)} AS user_id,
            {_sentiment_sql(db)} AS sentiment,
            NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') AS bde_key,
            NULLIF(TRIM(COALESCE(fd.rfmm_cluster, '')), '') AS rfmm_key,
            NULLIF(TRIM(COALESCE(fd.zone, '')), '') AS zone_key,
            NULLIF(TRIM(COALESCE(fd.division, '')), '') AS division_key,
            NULLIF(TRIM(COALESCE(fb.product_name, '')), '') AS product_name,
            COALESCE(fb.group_type, '') AS group_type,
            COALESCE(fb.ai_summary, '') AS ai_summary,
            {_verbatim_sql(db)} AS verbatim_quote,
            COALESCE((
                SELECT {tag_agg}
                FROM feedback_tag_link ftl
                JOIN feedback_tags ft ON ft.tag_id = ftl.tag_id
                WHERE ftl.feedback_id = fb.id
            ), '') AS tags
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
          {extra_where}
        """
    )
    return sql, call_date


def gather_insights(
    db: Session,
    *,
    start: date,
    end: date,
    grain: str,
    grain_key: str,
) -> list[dict[str, Any]]:
    """Load compact insight rows for a leaf cell. Never includes transcripts."""
    if grain not in INSIGHT_GRAINS:
        raise ValueError(f"{grain} must be built from child summaries, not insights")

    parsed = parse_insight_key(grain, grain_key)
    clauses: list[str] = []
    params: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat()}
    if parsed.get("geo_key"):
        clauses.append("NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') = :geo_key")
        params["geo_key"] = parsed["geo_key"]
    group_sql, group_params = _group_filter(parsed.get("group_type"))
    if group_sql:
        clauses.append(group_sql.replace(" AND ", "", 1))
        params.update(group_params)
    if parsed.get("product_name"):
        clauses.append("NULLIF(TRIM(COALESCE(fb.product_name, '')), '') = :product_name")
        params["product_name"] = parsed["product_name"]
    if parsed.get("tag_id"):
        clauses.append(
            "EXISTS ("
            " SELECT 1 FROM feedback_tag_link ftl"
            " WHERE ftl.feedback_id = fb.id"
            " AND ftl.tag_id = CAST(:tag_id AS INTEGER)"
            ")"
        )
        params["tag_id"] = parsed["tag_id"]
    extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql, _call_date = _insight_select_sql(db, extra)
    rows = db.execute(sql, params).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["sentiment"] = row_sentiment(item)
        out.append(item)
    return out


def list_hierarchy_nodes(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[dict[str, Optional[str]]]:
    """Geo keys that actually have insights in the period — skip empty BDEs/clusters."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT
            NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') AS bde_key,
            NULLIF(TRIM(COALESCE(fd.rfmm_cluster, '')), '') AS rfmm_key,
            NULLIF(TRIM(COALESCE(fd.zone, '')), '') AS zone_key,
            NULLIF(TRIM(COALESCE(fd.division, '')), '') AS division_key
        FROM file_details fd
        JOIN feedbacks fb ON fb.job_id = fd.job_id
        WHERE {call_date} BETWEEN :start AND :end
          {group_sql}
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    return [dict(row) for row in rows]


def list_groups(db: Session, start: date, end: date) -> list[str]:
    """Known PDT / USER / DEALER labels that have insights in the period."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    sql = text(
        f"""
        SELECT DISTINCT COALESCE(fb.group_type, '') AS group_type
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
        """
    )
    rows = db.execute(sql, {"start": start.isoformat(), "end": end.isoformat()}).mappings().all()
    seen: list[str] = []
    for row in rows:
        label = group_label(group_token(str(row.get("group_type") or "")))
        if label and label not in seen:
            seen.append(label)
    return seen


def list_product_keys(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[str]:
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT NULLIF(TRIM(COALESCE(fb.product_name, '')), '') AS product_name
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
          AND NULLIF(TRIM(COALESCE(fb.product_name, '')), '') IS NOT NULL
          {group_sql}
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    return [str(row["product_name"]) for row in rows if row.get("product_name")]


def list_tag_keys(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[dict[str, str]]:
    """Distinct taxonomy tags that appear on insights in the period."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT ft.tag_id AS grain_key, ft.tag_name AS grain_label
        FROM feedback_tag_link ftl
        JOIN feedback_tags ft ON ft.tag_id = ftl.tag_id
        JOIN feedbacks fb ON fb.id = ftl.feedback_id
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
          AND ft.tag_id IS NOT NULL
          {group_sql}
        ORDER BY ft.tag_id
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    out: list[dict[str, str]] = []
    for row in rows:
        if row.get("grain_key") is None:
            continue
        out.append({
            "grain_key": str(row["grain_key"]),
            "grain_label": str(row.get("grain_label") or row["grain_key"]),
        })
    return out


def list_cube_keys(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[dict[str, Optional[str]]]:
    """Sparse geo × product × tag × group cells that have insights in the period."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT
            COALESCE(fb.group_type, '') AS group_type,
            NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') AS bde_key,
            NULLIF(TRIM(COALESCE(fd.rfmm_cluster, '')), '') AS rfmm_key,
            NULLIF(TRIM(COALESCE(fd.zone, '')), '') AS zone_key,
            NULLIF(TRIM(COALESCE(fd.division, '')), '') AS division_key,
            NULLIF(TRIM(COALESCE(fb.product_name, '')), '') AS product_name,
            ft.tag_id AS tag_id,
            ft.tag_name AS tag_name
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        JOIN feedback_tag_link ftl ON ftl.feedback_id = fb.id
        JOIN feedback_tags ft ON ft.tag_id = ftl.tag_id
        WHERE {call_date} BETWEEN :start AND :end
          AND NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') IS NOT NULL
          AND ft.tag_id IS NOT NULL
          {group_sql}
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    out: list[dict[str, Optional[str]]] = []
    for row in rows:
        item = dict(row)
        if item.get("tag_id") is not None:
            item["tag_id"] = str(item["tag_id"])
        out.append(item)
    return out


def lines_from_insights(rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    raw_lines = [compact_line(row) for row in rows]
    lines = dedup_lines(raw_lines)
    highlights = rollup_from_rows(rows)
    highlights["deduped_count"] = len(lines)
    return lines, highlights
