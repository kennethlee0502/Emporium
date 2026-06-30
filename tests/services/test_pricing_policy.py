# Pricing policy regression tests (CLAUDE.md S3.3, S5.3).
#
# Built against the real, ingested catalog.json - these are the actual
# stock/available contradictions and price-state anomalies documented in
# CLAUDE.md S7, not synthetic fixtures.

from pathlib import Path

import pytest

from app.ingestion.loader import load_catalog_from_file
from app.indexing.catalog_index import build_catalog_index
from app.services.pricing_policy import is_purchasable

CATALOG_PATH = Path(__file__).resolve().parents[2] / "catalog.json"


@pytest.fixture(scope="module")
def index():
    result = load_catalog_from_file(CATALOG_PATH)
    return build_catalog_index(result.valid_records)


def test_out_of_stock_but_listed_available_is_purchasable(index):
    # prod_stock_001: stock_qty 0, available True - `available` is the
    # authority, not stock_qty, so backorder/pre-sale stays purchasable.
    entity = index.get_by_id("prod_stock_001")
    assert entity.stock_qty == 0
    assert entity.available is True
    assert is_purchasable(entity) is True


def test_in_stock_but_unavailable_is_not_purchasable(index):
    # prod_stock_002: stock_qty 14, available False - a QA hold/embargo
    # blocks purchase even though physical stock exists.
    entity = index.get_by_id("prod_stock_002")
    assert entity.stock_qty == 14
    assert entity.available is False
    assert is_purchasable(entity) is False


def test_non_positive_price_is_never_purchasable(index):
    # prod_zero_001: price 0.0, available True - internal/sample record,
    # excluded regardless of its available flag.
    entity = index.get_by_id("prod_zero_001")
    assert entity.available is True
    assert is_purchasable(entity) is False


def test_normal_available_product_is_purchasable(index):
    entity = index.get_by_id("prod_001")
    assert is_purchasable(entity) is True


def test_normal_available_bundle_is_purchasable(index):
    entity = index.get_by_id("bundle_001")
    assert is_purchasable(entity) is True


def test_gift_cards_are_purchasable_via_available_flag_alone(index):
    # Gift cards are denomination-priced (price_state NULL by design), so
    # price_state must NOT gate purchasability the way it does for Product/Bundle.
    for record_id in ("gift_001", "gift_002"):
        entity = index.get_by_id(record_id)
        assert entity.price is None
        assert entity.available is True
        assert is_purchasable(entity) is True


def test_null_price_product_is_not_purchasable(index):
    # prod_null_001: made-to-order, price intentionally null - cannot be
    # sold through the standard purchasable path without a quoted price.
    entity = index.get_by_id("prod_null_001")
    assert is_purchasable(entity) is False


def test_missing_price_product_is_not_purchasable(index):
    # prod_noprice_001: price key absent entirely (schema defect) - same
    # outcome as null, even though the two states are tracked distinctly.
    entity = index.get_by_id("prod_noprice_001")
    assert is_purchasable(entity) is False


def test_pages_are_never_purchasable(index):
    entity = index.get_by_id("page_001")
    assert is_purchasable(entity) is False


def test_collections_are_never_purchasable(index):
    entity = index.get_by_id("coll_001")
    assert is_purchasable(entity) is False
