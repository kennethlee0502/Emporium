# search_catalog core filtering regression tests (CLAUDE.md S5.2, S3.3).
#
# Integration tests through the real HTTP route (POST /v1/tools/search),
# against the real ingested catalog.json - all ids/counts/prices below were
# read out of the live index before being written as assertions.

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def search(client, **payload):
    response = client.post("/v1/tools/search", json=payload)
    return response


def test_market_id_is_required_at_the_http_layer(client):
    response = client.post("/v1/tools/search", json={"category": "apparel"})
    assert response.status_code == 422


def test_cross_market_leakage_is_impossible(client):
    response = search(client, market_id="us", category="apparel", limit=100)
    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["results"]]
    assert body["total_matches"] == 36
    assert "prod_000" in ids
    assert "prod_000_fr" not in ids  # same product group, wrong market
    assert "prod_eur_001" not in ids  # fr-only product, must never appear under us


def test_unknown_category_returns_an_empty_dataset_not_an_error(client):
    response = search(client, market_id="us", category="totally-fake-category")
    assert response.status_code == 200
    body = response.json()
    assert body["total_matches"] == 0
    assert body["results"] == []


def test_category_facet_filters_to_exactly_the_expected_ids(client):
    response = search(client, market_id="us", category="footwear", limit=10)
    body = response.json()
    ids = {item["id"] for item in body["results"]}
    assert ids == {"prod_021", "prod_022", "prod_023", "prod_024", "prod_025"}
    assert body["total_matches"] == 5


def test_tags_any_match_filters_correctly(client):
    response = search(client, market_id="us", tags=["black"], limit=100)
    ids = sorted(item["id"] for item in response.json()["results"])
    assert ids == [
        "prod_000", "prod_003", "prod_005", "prod_009", "prod_014", "prod_017",
        "prod_019", "prod_022", "prod_025", "prod_027", "prod_037",
        "prod_inject_002", "prod_stock_002", "prod_str_002",
    ]


def test_price_bounds_are_inclusive(client):
    response = search(client, market_id="us", min_price=39.7, max_price=39.7, limit=100)
    ids = [item["id"] for item in response.json()["results"]]
    assert ids == ["prod_001"]


def test_in_stock_only_uses_purchasability_policy_not_raw_stock_qty(client):
    # prod_stock_001: stock_qty 0, available True -> purchasable, must be included.
    # prod_stock_002: stock_qty 14, available False -> not purchasable, must be excluded.
    # A naive `stock_qty > 0` check would get both of these backwards.
    response = search(client, market_id="us", category="apparel", in_stock_only=True, limit=100)
    ids = {item["id"] for item in response.json()["results"]}
    assert "prod_stock_001" in ids
    assert "prod_stock_002" not in ids


def test_sort_by_price_asc_is_exact(client):
    response = search(client, market_id="us", category="footwear", sort_by="price_asc", limit=10)
    ids = [item["id"] for item in response.json()["results"]]
    assert ids == ["prod_024", "prod_021", "prod_023", "prod_025", "prod_022"]


def test_sort_by_price_desc_is_exact(client):
    response = search(client, market_id="us", category="footwear", sort_by="price_desc", limit=10)
    ids = [item["id"] for item in response.json()["results"]]
    assert ids == ["prod_022", "prod_025", "prod_023", "prod_021", "prod_024"]


def test_sort_by_rating_desc_is_exact_with_stable_tie_break(client):
    # prod_021 and prod_025 are tied at rating 4.8; a stable sort preserves
    # their original catalog order (021 before 025) rather than re-ordering ties.
    response = search(client, market_id="us", category="footwear", sort_by="rating_desc", limit=10)
    ids = [item["id"] for item in response.json()["results"]]
    assert ids == ["prod_021", "prod_025", "prod_024", "prod_023", "prod_022"]


def test_limit_slices_results_but_total_matches_reflects_the_full_count(client):
    response = search(client, market_id="us", limit=5)
    body = response.json()
    assert len(body["results"]) == 5
    assert body["total_matches"] == 59


def test_collections_and_pages_never_appear_in_search_results(client):
    response = search(client, market_id="us", limit=100)
    types = {item["type"] for item in response.json()["results"]}
    assert types <= {"product", "gift_card", "bundle"}


# --- Task 10: free-text relevance (RapidFuzz) + duplicate advisory ---


def test_typo_query_still_finds_the_intended_item(client):
    # "Crew Te" is a typo/truncation of "Crew Tee" - must still surface the
    # Everyday Crew Tee family via fuzzy matching, not exact substring match.
    response = search(client, market_id="us", query="Crew Te", limit=10)
    ids = {item["id"] for item in response.json()["results"]}
    assert {"prod_000", "prod_001", "prod_002"} <= ids


def test_typo_query_across_word_order_and_misspelling(client):
    # "hodie black" - misspelled "hoodie" plus a color term, no exact substring
    # match anywhere in the catalog text.
    response = search(client, market_id="us", query="hodie black", limit=10)
    ids = {item["id"] for item in response.json()["results"]}
    assert "prod_005" in ids  # Heavyweight Hoodie - Black


def test_unrelated_query_returns_no_matches(client):
    # A short "real words" nonsense phrase ("xyz totally unrelated nonsense")
    # was tried first and rejected as a fixture: it scored a borderline 45.0
    # against prod_inject_001's long, sentence-heavy description purely from
    # incidental character/word overlap (a WRatio length-sensitivity
    # artifact, not the injection payload being "obeyed" - this service
    # never interprets catalog text as instructions). A clearly gibberish
    # phrase keeps a wide safety margin (~36 max) below the 45.0 threshold
    # across the entire catalog.
    response = search(client, market_id="us", query="qzxv flibbertigibbet wobble", limit=10)
    body = response.json()
    assert body["total_matches"] == 0
    assert body["results"] == []


def test_relevance_sort_orders_by_match_quality_when_query_given(client):
    response = search(client, market_id="us", query="classic white tee", sort_by="relevance", limit=20)
    ids = [item["id"] for item in response.json()["results"]]
    # The three near-identical "Classic White Tee" records are the best
    # possible textual match for this exact query and must rank first.
    assert ids[:3] == ["prod_dupe_a", "prod_dupe_b", "prod_dupe_c"]


def test_duplicate_advisory_cross_references_siblings_without_merging(client):
    response = search(client, market_id="us", query="classic white tee", limit=20)
    by_id = {item["id"]: item for item in response.json()["results"]}

    # All three are returned independently - never merged into one entry -
    # with different prices/stock preserved (CLAUDE.md S3.4).
    assert {"prod_dupe_a", "prod_dupe_b", "prod_dupe_c"} <= by_id.keys()
    assert by_id["prod_dupe_a"]["price"] == 24.0
    assert by_id["prod_dupe_b"]["price"] == 26.0
    assert by_id["prod_dupe_c"]["price"] == 24.0

    assert sorted(by_id["prod_dupe_a"]["possible_duplicate_ids"]) == ["prod_dupe_b", "prod_dupe_c"]
    assert sorted(by_id["prod_dupe_b"]["possible_duplicate_ids"]) == ["prod_dupe_a", "prod_dupe_c"]
    assert sorted(by_id["prod_dupe_c"]["possible_duplicate_ids"]) == ["prod_dupe_a", "prod_dupe_b"]


def test_color_variant_siblings_are_not_falsely_flagged_as_duplicates(client):
    # "Everyday Crew Tee - White/Black/Navy" are legitimately distinct
    # products, not data-quality duplicates - must not be cross-referenced.
    response = search(client, market_id="us", query="everyday crew tee", limit=20)
    by_id = {item["id"]: item for item in response.json()["results"]}
    for product_id in ("prod_000", "prod_001", "prod_002"):
        assert by_id[product_id]["possible_duplicate_ids"] is None


def test_items_without_duplicates_have_a_null_advisory_field(client):
    response = search(client, market_id="us", category="footwear", limit=10)
    for item in response.json()["results"]:
        assert item["possible_duplicate_ids"] is None
