"""Month / quarter / year keys and date bounds for period summaries."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Optional

KEY_SEP = "::"
GROUP_LABELS = ("PDT GROUP", "USER GROUP", "DEALER GROUP")
GROUP_TOKENS = ("PDT", "USER", "DEALER")
_LABEL_TO_TOKEN = {
    "PDT GROUP": "PDT",
    "USER GROUP": "USER",
    "DEALER GROUP": "DEALER",
    "PDT": "PDT",
    "USER": "USER",
    "DEALER": "DEALER",
}
_TOKEN_TO_LABEL = {
    "PDT": "PDT GROUP",
    "USER": "USER GROUP",
    "DEALER": "DEALER GROUP",
}

GEO_GRAINS = ("bde", "rfmm", "zone", "division")
CUBE_GRAINS = ("bde_pt", "rfmm_pt", "zone_pt", "div_pt")
PRODUCT_SLICE_GRAINS = ("bde_p", "rfmm_p", "zone_p", "div_p")
TAG_SLICE_GRAINS = ("bde_t", "rfmm_t", "zone_t", "div_t")
GRAINS = (
    *GEO_GRAINS,
    "product",
    "tag",
    *CUBE_GRAINS,
    *PRODUCT_SLICE_GRAINS,
    *TAG_SLICE_GRAINS,
)
PERIOD_TYPES = ("month", "quarter", "year")
CHILD_GRAIN = {
    "rfmm": "bde",
    "zone": "rfmm",
    "division": "zone",
    "rfmm_pt": "bde_pt",
    "zone_pt": "rfmm_pt",
    "div_pt": "zone_pt",
    "rfmm_p": "bde_p",
    "zone_p": "rfmm_p",
    "div_p": "zone_p",
    "rfmm_t": "bde_t",
    "zone_t": "rfmm_t",
    "div_t": "zone_t",
}
PARENT_GRAIN = {child: parent for parent, child in CHILD_GRAIN.items()}
HIERARCHY_ORDER = GEO_GRAINS
LEAF_GRAINS = ("bde", "product", "tag", "bde_pt", "bde_p", "bde_t")
TIME_ROLLUP_GRAINS = GRAINS
INSIGHT_GRAINS = {"bde", "product", "tag", "bde_pt", "bde_p", "bde_t"}
MAX_MONTH_CELLS = 4000

_GEO_FAMILY = {
    "bde": ("bde_p", "bde_t", "bde_pt"),
    "rfmm": ("rfmm_p", "rfmm_t", "rfmm_pt"),
    "zone": ("zone_p", "zone_t", "zone_pt"),
    "division": ("div_p", "div_t", "div_pt"),
}


def group_token(value: Optional[str]) -> Optional[str]:
    text = " ".join((value or "").split()).strip().upper()
    if not text:
        return None
    if text in _LABEL_TO_TOKEN:
        return _LABEL_TO_TOKEN[text]
    compact = text.replace(" GROUP", "").strip()
    return _LABEL_TO_TOKEN.get(compact)


def group_label(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return _TOKEN_TO_LABEL.get(token.upper())


def scoped_key(*parts: Optional[str]) -> str:
    chunks = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    if not chunks:
        raise ValueError("scoped_key requires at least one part")
    return KEY_SEP.join(chunks)


def split_key(grain_key: str) -> list[str]:
    return [part for part in (grain_key or "").split(KEY_SEP)]


def key_group_token(grain_key: Optional[str]) -> Optional[str]:
    parts = split_key(grain_key or "")
    if len(parts) >= 2 and parts[1] in GROUP_TOKENS:
        return parts[1]
    return None


def display_key(grain_key: Optional[str]) -> str:
    """Geo or product/tag identity without group / cube suffix."""
    parts = split_key(grain_key or "")
    if not parts:
        return ""
    return parts[0]


def matches_group(grain_key: Optional[str], token: Optional[str]) -> bool:
    if not token:
        return True
    found = key_group_token(grain_key)
    if found is None:
        return True
    return found == token


def slice_grains_for_geo(geo_grain: Optional[str]) -> dict[str, str]:
    if not geo_grain:
        return {"product": "product", "tag": "tag", "cube": "product"}
    product, tag, cube = _GEO_FAMILY[geo_grain]
    return {"product": product, "tag": tag, "cube": cube}


def key_suffix(grain_key: Optional[str]) -> str:
    parts = split_key(grain_key or "")
    return KEY_SEP.join(parts[1:]) if len(parts) > 1 else ""


def with_geo(geo: Optional[str], grain_key: Optional[str]) -> Optional[str]:
    if not geo:
        return None
    suffix = key_suffix(grain_key)
    return scoped_key(geo, suffix) if suffix else geo


def mixed_key(geo: Optional[str], token: Optional[str]) -> str:
    if not geo:
        raise ValueError("mixed_key requires a geo identity")
    return scoped_key(geo, token) if token else geo


def parse_insight_key(grain: str, grain_key: str) -> dict[str, Optional[str]]:
    """Decode a stored grain_key into gather filters. Accepts unscoped legacy keys."""
    parts = split_key(grain_key)
    token = parts[1] if len(parts) >= 2 and parts[1] in GROUP_TOKENS else None
    group = group_label(token) if token else None
    geo = parts[0] if parts else None
    if grain in {"bde", "product", "tag"}:
        identity = parts[0] if parts else grain_key
        if grain == "bde":
            return {"geo_key": identity, "group_type": group, "product_name": None, "tag_id": None}
        if grain == "product":
            return {"geo_key": None, "group_type": group, "product_name": identity, "tag_id": None}
        return {"geo_key": None, "group_type": group, "product_name": None, "tag_id": identity}
    if grain == "bde_p":
        product = KEY_SEP.join(parts[2:]) if token and len(parts) >= 3 else KEY_SEP.join(parts[1:])
        return {"geo_key": geo, "group_type": group, "product_name": product or None, "tag_id": None}
    if grain == "bde_t":
        tag_id = parts[-1] if len(parts) >= 3 else None
        return {"geo_key": geo, "group_type": group, "product_name": None, "tag_id": tag_id}
    if grain == "bde_pt":
        tag_id = parts[-1] if len(parts) >= 4 else None
        product = KEY_SEP.join(parts[2:-1]) if token and len(parts) >= 4 else None
        return {"geo_key": geo, "group_type": group, "product_name": product, "tag_id": tag_id}
    raise ValueError(f"{grain} is not an insight grain")


def utc_today(now: Optional[datetime] = None) -> date:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.date()


def pad_month(month: int) -> str:
    return f"{month:02d}"


def month_key(value: date) -> str:
    return f"{value.year}-{pad_month(value.month)}"


def quarter_number(value: date) -> int:
    return (value.month - 1) // 3 + 1


def quarter_key(value: date) -> str:
    return f"{value.year}-Q{quarter_number(value)}"


def year_key(value: date) -> str:
    return str(value.year)


def current_month_key(now: Optional[datetime] = None) -> str:
    return month_key(utc_today(now))


def parse_month_key(key: str) -> tuple[int, int]:
    year_text, month_text = key.split("-", 1)
    year, month = int(year_text), int(month_text)
    if month < 1 or month > 12:
        raise ValueError(f"Invalid month key {key}")
    return year, month


def parse_quarter_key(key: str) -> tuple[int, int]:
    year_text, quarter_text = key.split("-Q", 1)
    year, quarter = int(year_text), int(quarter_text)
    if quarter < 1 or quarter > 4:
        raise ValueError(f"Invalid quarter key {key}")
    return year, quarter


def month_bounds(key: str) -> tuple[date, date]:
    year, month = parse_month_key(key)
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def quarter_bounds(key: str) -> tuple[date, date]:
    year, quarter = parse_quarter_key(key)
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    return date(year, start_month, 1), date(year, end_month, monthrange(year, end_month)[1])


def year_bounds(key: str) -> tuple[date, date]:
    year = int(key)
    return date(year, 1, 1), date(year, 12, 31)


def bounds_for(period_type: str, period_key: str) -> tuple[date, date]:
    if period_type == "month":
        return month_bounds(period_key)
    if period_type == "quarter":
        return quarter_bounds(period_key)
    if period_type == "year":
        return year_bounds(period_key)
    raise ValueError(f"Unknown period_type {period_type}")


def previous_month_key(key: str) -> str:
    year, month = parse_month_key(key)
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{pad_month(month - 1)}"


def previous_quarter_key(key: str) -> str:
    year, quarter = parse_quarter_key(key)
    if quarter == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{quarter - 1}"


def previous_year_key(key: str) -> str:
    return str(int(key) - 1)


def previous_period(period_type: str, period_key: str) -> tuple[str, str]:
    if period_type == "month":
        return "month", previous_month_key(period_key)
    if period_type == "quarter":
        return "quarter", previous_quarter_key(period_key)
    if period_type == "year":
        return "year", previous_year_key(period_key)
    raise ValueError(f"Unknown period_type {period_type}")


def child_month_keys(quarter_key_value: str) -> list[str]:
    year, quarter = parse_quarter_key(quarter_key_value)
    start = (quarter - 1) * 3 + 1
    return [f"{year}-{pad_month(start + offset)}" for offset in range(3)]


def child_quarter_keys(year_key_value: str) -> list[str]:
    year = int(year_key_value)
    return [f"{year}-Q{quarter}" for quarter in range(1, 5)]


def quarter_key_from_month(month_key_value: str) -> str:
    year, month = parse_month_key(month_key_value)
    return f"{year}-Q{(month - 1) // 3 + 1}"


def year_key_from_month(month_key_value: str) -> str:
    year, _month = parse_month_key(month_key_value)
    return str(year)


def is_last_month_of_quarter(month_key_value: str) -> bool:
    _year, month = parse_month_key(month_key_value)
    return month % 3 == 0


def is_last_month_of_year(month_key_value: str) -> bool:
    _year, month = parse_month_key(month_key_value)
    return month == 12


def infer_period(start: date, end: date) -> tuple[str, str]:
    """Map a start/end date range to month, quarter, or year."""
    if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31 and start.year == end.year:
        return "year", str(start.year)
    quarter = quarter_number(start)
    q_start, q_end = quarter_bounds(f"{start.year}-Q{quarter}")
    if start == q_start and end == q_end:
        return "quarter", f"{start.year}-Q{quarter}"
    return "month", month_key(start)


def resolve_grain(
    *,
    fme_code: Optional[str] = None,
    cluster: Optional[str] = None,
    zone: Optional[str] = None,
    division: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Most specific geo grain from report filters."""
    if fme_code:
        return "bde", fme_code
    if cluster:
        return "rfmm", cluster
    if zone:
        return "zone", zone
    if division:
        return "division", division
    return None, None


def list_grain_for_filters(
    *,
    fme_code: Optional[str] = None,
    cluster: Optional[str] = None,
    zone: Optional[str] = None,
    division: Optional[str] = None,
) -> str:
    """Grain to list on the summaries page (children of current selection)."""
    if fme_code:
        return "bde"
    if cluster:
        return "bde"
    if zone:
        return "rfmm"
    if division:
        return "zone"
    return "division"
