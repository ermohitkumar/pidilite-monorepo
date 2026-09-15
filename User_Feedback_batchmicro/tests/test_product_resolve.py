"""Unit tests for master-catalog product name validation."""
from types import SimpleNamespace

from services.shared.product_resolve import (
    enforce_master_product_names,
    resolve_product_from_master,
)


def _products():
    return [
        SimpleNamespace(id=1, product_name="Fevicol Marine", short_code="F-M"),
        SimpleNamespace(id=2, product_name="Fevicol SH", short_code="F-S"),
        SimpleNamespace(id=3, product_name="Fevicol Hi-per Star", short_code="F-HS"),
        SimpleNamespace(id=4, product_name="Fevicol Relam", short_code="F-R"),
    ]


def test_exact_name_match():
    name, pid = resolve_product_from_master("Fevicol Marine", _products())
    assert name == "Fevicol Marine"
    assert pid == 1


def test_case_insensitive_and_short_code():
    name, pid = resolve_product_from_master("fevicol sh", _products())
    assert name == "Fevicol SH"
    assert pid == 2
    name2, pid2 = resolve_product_from_master("F-HS", _products())
    assert name2 == "Fevicol Hi-per Star"
    assert pid2 == 3


def test_alias_unique_match():
    name, pid = resolve_product_from_master("Marine", _products())
    assert name == "Fevicol Marine"
    assert pid == 1


def test_nail_free_ultra_quick_maps_to_catalog():
    products = _products() + [
        SimpleNamespace(id=5, product_name="Fevicol Nail Free", short_code="F-NF"),
    ]
    name, pid = resolve_product_from_master("Nail-Free Ultra Quick", products)
    assert name == "Fevicol Nail Free"
    assert pid == 5


def test_reject_unknown_product():
    name, pid = resolve_product_from_master("Some Fake Glue", _products())
    assert name is None
    assert pid is None


def test_user_dealer_allow_null_product():
    insights = [
        {"group_type": "USER GROUP", "product_name": None, "summary": "meet"},
        {"group_type": "DEALER GROUP", "product_name": "Invented", "summary": "stock"},
        {"group_type": "PDT GROUP", "product_name": "Invented", "summary": "glue"},
        {"group_type": "PDT GROUP", "product_name": "Marine", "summary": "ok"},
    ]
    enforce_master_product_names(insights, _products())
    assert insights[0]["product_name"] is None
    assert insights[1]["product_name"] is None  # rejected invented; null OK for dealer
    assert insights[2]["product_name"] is None
    assert insights[2].get("_product_validation_error")
    assert insights[3]["product_name"] == "Fevicol Marine"


def test_reject_competitor_name_like_century():
    name, pid = resolve_product_from_master("Century", _products())
    assert name is None
    assert pid is None
    insights = [{"group_type": "PDT GROUP", "product_name": "Century", "summary": "comp"}]
    enforce_master_product_names(insights, _products())
    assert insights[0]["product_name"] is None
