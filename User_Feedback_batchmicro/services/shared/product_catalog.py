"""Build the compact product catalog TSV used by translation and insights."""
from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from repositories import batch_repository


def _usable_product_name(name: str | None) -> str | None:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 50:
        return None
    name_lower = cleaned.lower()
    if any(keyword in name_lower for keyword in settings.MARKETING_KEYWORDS):
        return None
    return cleaned


def build_product_tsv(db: Session, include_description: bool = True) -> str:
    """Convert active products into a token-efficient TSV string.

    Format: sku|Product_Name[|description]
    Skips long marketing taglines that leaked through the scraper.
    """
    products = batch_repository.get_active_products(db)
    tsv_lines: list[str] = []
    for product in products:
        name = _usable_product_name(product.product_name)
        if not name:
            continue
        sku = product.short_code or str(product.id)[:8]
        if include_description and product.description:
            tsv_lines.append(f"{sku}|{name}|{product.description}")
        else:
            tsv_lines.append(f"{sku}|{name}")
    return "\n".join(tsv_lines)


def stt_adaptation_phrases(db: Session, limit: int | None = None) -> list[str]:
    """Active product names for Chirp 3 SpeechAdaptation (max 1000 phrases)."""
    max_phrases = limit if limit is not None else settings.STT_ADAPTATION_MAX_PHRASES
    max_phrases = max(0, min(int(max_phrases or 0), 1000))
    if max_phrases == 0:
        return []

    phrases: list[str] = []
    seen: set[str] = set()
    for product in batch_repository.get_active_products(db):
        name = _usable_product_name(product.product_name)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(name)
        if len(phrases) >= max_phrases:
            break
    return phrases
