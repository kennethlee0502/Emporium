# Entity-model regression tests against the known catalog.json anomalies (CLAUDE.md S7).
# Sanitization/text-repair are NOT exercised here - that's Task 2/3. This file only
# proves the discriminated-union + price-state parsing in app/models/entities.py.

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.entities import (
    Bundle,
    Collection,
    GiftCard,
    Page,
    PriceState,
    Product,
    catalog_entity_adapter,
)

CATALOG_PATH = Path(__file__).resolve().parents[2] / "catalog.json"


@pytest.fixture(scope="module")
def catalog_by_id():
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {record["id"]: record for record in raw}


def parse(catalog_by_id, record_id):
    return catalog_entity_adapter.validate_python(catalog_by_id[record_id])


def test_entire_catalog_parses_without_error(catalog_by_id):
    for record_id in catalog_by_id:
        parse(catalog_by_id, record_id)


def test_string_price_is_coerced_to_float(catalog_by_id):
    for record_id in ("prod_str_001", "prod_str_002"):
        entity = parse(catalog_by_id, record_id)
        assert isinstance(entity, Product)
        assert isinstance(entity.price, float)
        assert entity.price_state is PriceState.NORMAL


def test_explicit_null_price_is_preserved_as_null_state(catalog_by_id):
    entity = parse(catalog_by_id, "prod_null_001")
    assert entity.price is None
    assert entity.price_state is PriceState.NULL


def test_gift_cards_are_null_price_state(catalog_by_id):
    for record_id in ("gift_001", "gift_002"):
        entity = parse(catalog_by_id, record_id)
        assert isinstance(entity, GiftCard)
        assert entity.price is None
        assert entity.price_state is PriceState.NULL
        assert len(entity.denominations) > 0


def test_missing_price_key_is_distinct_from_null(catalog_by_id):
    entity = parse(catalog_by_id, "prod_noprice_001")
    assert entity.price is None
    assert entity.price_state is PriceState.MISSING  # not PriceState.NULL


def test_non_positive_price_is_flagged(catalog_by_id):
    entity = parse(catalog_by_id, "prod_zero_001")
    assert entity.price == 0.0
    assert entity.price_state is PriceState.NON_POSITIVE


def test_stock_and_available_are_independent_not_derived(catalog_by_id):
    oversold_but_listed_available = parse(catalog_by_id, "prod_stock_001")
    assert oversold_but_listed_available.stock_qty == 0
    assert oversold_but_listed_available.available is True

    in_stock_but_paused = parse(catalog_by_id, "prod_stock_002")
    assert in_stock_but_paused.stock_qty == 14
    assert in_stock_but_paused.available is False


def test_near_duplicate_names_remain_distinct_records(catalog_by_id):
    dupe_a = parse(catalog_by_id, "prod_dupe_a")
    dupe_b = parse(catalog_by_id, "prod_dupe_b")
    dupe_c = parse(catalog_by_id, "prod_dupe_c")
    assert {dupe_a.id, dupe_b.id, dupe_c.id} == {"prod_dupe_a", "prod_dupe_b", "prod_dupe_c"}
    assert (dupe_a.price, dupe_b.price, dupe_c.price) == (24.0, 26.0, 24.0)


def test_market_siblings_keep_independent_localized_prices(catalog_by_id):
    us = parse(catalog_by_id, "prod_000")
    fr = parse(catalog_by_id, "prod_000_fr")
    uk = parse(catalog_by_id, "prod_000_uk")
    assert us.product_group_id == fr.product_group_id == uk.product_group_id == "prod_000"
    assert (us.price, us.currency) == (52.18, "USD")
    assert (fr.price, fr.currency) == (48.0, "EUR")
    assert (uk.price, uk.currency) == (41.0, "GBP")


def test_missing_category_and_tags_default_to_none(catalog_by_id):
    entity = parse(catalog_by_id, "prod_noschema_001")
    assert entity.category is None
    assert entity.tags is None


def test_html_description_parses_unsanitized_at_model_layer(catalog_by_id):
    # Sanitization is Task 3's job - the model only needs to accept the raw text.
    entity = parse(catalog_by_id, "prod_html_001")
    assert "<b>" in entity.description


def test_injection_payloads_parse_unsanitized_at_model_layer(catalog_by_id):
    # Same boundary note as above: flagging/stripping happens at ingestion, not here.
    system_injection = parse(catalog_by_id, "prod_inject_001")
    assert "SYSTEM:" in system_injection.description

    fake_turn_injection = parse(catalog_by_id, "prod_inject_002")
    assert isinstance(fake_turn_injection, Product)
    assert fake_turn_injection.top_review is not None
    assert "Assistant:" in fake_turn_injection.top_review


def test_collection_page_bundle_shapes(catalog_by_id):
    collection = parse(catalog_by_id, "coll_001")
    assert isinstance(collection, Collection)
    assert "prod_000" in collection.member_ids

    page = parse(catalog_by_id, "page_001")
    assert isinstance(page, Page)

    bundle = parse(catalog_by_id, "bundle_001")
    assert isinstance(bundle, Bundle)
    assert bundle.price_state is PriceState.NORMAL
    assert bundle.available is True


def test_market_id_is_required(catalog_by_id):
    record = dict(catalog_by_id["prod_001"])
    del record["market_id"]
    with pytest.raises(ValidationError):
        catalog_entity_adapter.validate_python(record)
