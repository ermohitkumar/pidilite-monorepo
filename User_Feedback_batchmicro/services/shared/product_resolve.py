"""Resolve LLM product names against the products master catalog."""
from __future__ import annotations

import logging
import re
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class _ProductLike(Protocol):
    id: Any
    product_name: str
    short_code: str | None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def resolve_product_from_master(
    raw_name: str | None,
    products: list[_ProductLike],
) -> tuple[str | None, int | None]:
    """
    Map an LLM product_name to a master catalog row.

    Returns (canonical_product_name, product_id) or (None, None) if not in master
    or the match is ambiguous.
    """
    if not raw_name or not str(raw_name).strip():
        return None, None
    if not products:
        return None, None

    key = _norm(str(raw_name))

    by_name = {_norm(p.product_name): p for p in products if p.product_name}
    if key in by_name:
        p = by_name[key]
        return p.product_name, int(p.id)

    by_code = {
        _norm(p.short_code): p
        for p in products
        if p.short_code and str(p.short_code).strip()
    }
    if key in by_code:
        p = by_code[key]
        return p.product_name, int(p.id)

    # Unique soft match: spoken alias is a trailing token of the canonical name
    # e.g. "Marine" → "Fevicol Marine", "SH" → "Fevicol SH"
    candidates: dict[Any, _ProductLike] = {}
    for p in products:
        pname = _norm(p.product_name)
        tokens = pname.replace("-", " ").split()
        if key in tokens or pname.endswith(" " + key) or pname.endswith(key):
            # Avoid matching very short keys against many products unless unique later
            candidates[p.id] = p
        # "Fevicol Hi-per Star" vs "Hyper Star" / "Hi-per Star"
        compact_name = pname.replace("-", "").replace(" ", "")
        compact_key = key.replace("-", "").replace(" ", "")
        if compact_key and compact_key in compact_name and len(compact_key) >= 4:
            candidates[p.id] = p
        # "Nail-Free Ultra Quick" → "Fevicol Nail Free"
        raw_tokens = set(key.replace("-", " ").split())
        catalog_tokens = [
            t for t in pname.replace("-", " ").split()
            if t not in {"fevicol"} and len(t) >= 3
        ]
        if catalog_tokens and set(catalog_tokens).issubset(raw_tokens):
            candidates[p.id] = p

    if len(candidates) == 1:
        p = next(iter(candidates.values()))
        return p.product_name, int(p.id)

    if candidates:
        logger.warning(
            "Ambiguous product_name %r matched %d master rows; rejecting",
            raw_name,
            len(candidates),
        )
    return None, None


def enforce_master_product_names(
    insights: list[dict],
    products: list[_ProductLike],
) -> list[dict]:
    """
    In-place product_name validation against the master catalog.

    Rules:
    - Any non-empty product_name must resolve to the master catalog (else null).
    - USER GROUP / DEALER GROUP: product_name may be null.
    - PDT GROUP: product_name must be a master catalog name when present.
      Competitor names (Century, etc.) are not catalog products and are cleared.
    """
    for item in insights:
        group = (item.get("group_type") or "").strip().upper()
        raw = item.get("product_name")
        canonical, product_id = resolve_product_from_master(raw, products)

        if raw and not canonical:
            logger.warning(
                "Rejected product_name not in master catalog: %r (group=%s)",
                raw,
                group or "?",
            )

        if group in {"USER GROUP", "DEALER GROUP", "USER", "DEALER"}:
            # Null allowed; keep only master-validated names
            item["product_name"] = canonical
            item["_resolved_product_id"] = product_id
            continue

        # PDT GROUP (and unknown): product_name must be from master when present;
        # null after rejection is a validation miss for PDT.
        item["product_name"] = canonical
        item["_resolved_product_id"] = product_id
        if not canonical:
            item["_product_validation_error"] = (
                "PDT GROUP requires product_name from master catalog"
            )
            logger.warning(
                "PDT insight missing master product_name (raw=%r): %s",
                raw,
                (item.get("summary") or "")[:120],
            )
    return insights
