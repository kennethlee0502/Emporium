# search_catalog core filtering regression tests (CLAUDE.md S5.2, S3.3).
#
# Integration tests through the real HTTP route (POST /tools/search),
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
    response = client.post("/tools/search", json=payload)
    return response


def test_market_id_is_required_at_the_http_layer(client):
    response = client.post("/tools/search", json={"category": "apparel"})
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
