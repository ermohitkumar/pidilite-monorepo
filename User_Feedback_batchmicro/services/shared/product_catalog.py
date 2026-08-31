"""Build the compact product catalog TSV used by translation and insights."""
from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from repositories import batch_repository


def build_product_tsv(db: Session, include_description: bool = True) -> str:
    """Convert active products into a token-efficient TSV string.

    Format: sku|Product_Name[|description]
    Skips long marketing taglines that leaked through the scraper.
    """
    products = batch_repository.get_active_products(db)
    tsv_lines: list[str] = []
    for product in products:
        sku = product.short_code or str(product.id)[:8]
        name = product.product_name or ""
        name_lower = name.lower()
        if len(name) > 50:
            continue
        if any(keyword in name_lower for keyword in settings.MARKETING_KEYWORDS):
            continue
        if include_description and product.description:
            tsv_lines.append(f"{sku}|{name}|{product.description}")
        else:
            tsv_lines.append(f"{sku}|{name}")
    return "\n".join(tsv_lines)
