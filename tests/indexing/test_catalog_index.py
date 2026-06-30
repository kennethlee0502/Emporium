# In-memory index regression tests (CLAUDE.md S2.3, S3.3).
#
# Built against the real, ingested catalog.json (loader output), not
# synthetic fixtures - these are the actual relational linkages the
# search/detail/resolution tools (Tasks 9-13) will depend on.

from pathlib import Path

import pytest

from app.ingestion.loader import load_catalog_from_file
from app.indexing.catalog_index import build_catalog_index

CATALOG_PATH = Path(__file__).resolve().parents[2] / "catalog.json"


@pytest.fixture(scope="module")
def index():
    result = load_catalog_from_file(CATALOG_PATH)
    return build_catalog_index(result.valid_records)


def test_primary_index_lookup_by_id(index):
    entity = index.get_by_id("prod_001")
    assert entity is not None
    assert entity.id == "prod_001"
    assert entity.name == "Everyday Crew Tee - White"


def test_primary_index_returns_none_for_unknown_id(index):
    assert index.get_by_id("does-not-exist") is None


def test_group_index_resolves_prod_000_market_siblings(index):
    siblings = index.get_group_siblings("prod_000")
    assert set(siblings.keys()) == {"us", "fr", "de", "uk"}
    assert siblings["us"].id == "prod_000"
    assert siblings["fr"].id == "prod_000_fr"
    assert siblings["de"].id == "prod_000_de"
    assert siblings["uk"].id == "prod_000_uk"
    # Independently authored regional prices, never FX-derived (CLAUDE.md S1.9).
    assert (siblings["us"].price, siblings["us"].currency) == (52.18, "USD")
    assert (siblings["fr"].price, siblings["fr"].currency) == (48.0, "EUR")
    assert (siblings["uk"].price, siblings["uk"].currency) == (41.0, "GBP")


def test_group_index_handles_products_with_no_localized_siblings(index):
    # prod_003 (Boxy Pocket Tee - Black) only ever exists in the us market.
    siblings = index.get_group_siblings("prod_003")
    assert set(siblings.keys()) == {"us"}


def test_group_index_returns_empty_mapping_for_unknown_group(index):
    assert index.get_group_siblings("no-such-group") == {}


def test_collection_resolves_via_primary_index_with_member_ids(index):
    collection = index.get_by_id("coll_001")
    assert collection.type == "collection"
    assert collection.market_id == "us"
    assert collection.category is None
    assert collection.member_ids == ["prod_000", "prod_004", "prod_eur_002"]
    # by_id is a flat, market-agnostic lookup, so every member_id resolves to
    # *an* entity here - prod_eur_002 is a real, valid id. The cross-market
    # mismatch (collection is "us", prod_eur_002 is "fr") is a business-rule
    # concern for Task 12's resolution_service, not a raw index lookup miss.
    resolved = [index.get_by_id(mid) for mid in collection.member_ids]
    assert [e.id for e in resolved] == ["prod_000", "prod_004", "prod_eur_002"]
    assert resolved[2].market_id == "fr"
    assert resolved[2].market_id != collection.market_id


def test_bundle_resolves_via_primary_index_with_members_and_tags(index):
    bundle = index.get_by_id("bundle_001")
    assert bundle.type == "bundle"
    assert bundle.category == "apparel"
    assert bundle.member_ids == ["prod_000", "prod_005", "prod_018"]
    assert bundle.tags == ["apparel", "bundle"]
    assert all(index.get_by_id(mid) is not None for mid in bundle.member_ids)


def test_market_category_index_facets_correctly(index):
    apparel_ids = index.get_ids_by_market_category("us", "apparel")
    assert "prod_000" in apparel_ids
    assert "prod_001" in apparel_ids
    # Footwear products must not leak into the apparel facet.
    assert "prod_021" not in apparel_ids


def test_market_category_index_buckets_missing_category_under_none(index):
    none_category_ids = index.get_ids_by_market_category("us", None)
    assert "coll_001" in none_category_ids
    assert "page_001" in none_category_ids
    assert "prod_noschema_001" in none_category_ids  # missing `category` key entirely


def test_market_category_index_is_market_scoped(index):
    us_apparel = index.get_ids_by_market_category("us", "apparel")
    fr_apparel = index.get_ids_by_market_category("fr", "apparel")
    assert "prod_000" in us_apparel
    assert "prod_000" not in fr_apparel
    assert "prod_000_fr" in fr_apparel


def test_tag_inverted_index_groups_matching_ids(index):
    black_ids = index.get_ids_by_tag("black")
    assert "prod_000" in black_ids
    assert "prod_003" in black_ids
    assert "bundle_001" in index.get_ids_by_tag("bundle")


def test_tag_inverted_index_returns_empty_for_unknown_tag(index):
    assert index.get_ids_by_tag("no-such-tag") == ()


def test_index_mappings_are_read_only(index):
    with pytest.raises(TypeError):
        index.by_id["hacked"] = "should not be allowed"
    with pytest.raises(TypeError):
        index.by_tag["black"] = ()
    with pytest.raises(TypeError):
        index.by_market_category[("us", "apparel")] = ()
    with pytest.raises(TypeError):
        index.by_group["prod_000"]["us"] = "should not be allowed"


def test_index_covers_every_valid_record(index):
    result = load_catalog_from_file(CATALOG_PATH)
    assert len(index.by_id) == len(result.valid_records)
