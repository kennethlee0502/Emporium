# get_product_details / cross-market resolution regression tests
# (CLAUDE.md S1.9, S5.2). Integration tests through the real HTTP route
# (POST /tools/details), against the real ingested catalog.json - every
# id/price/reason below was read out of the live resolution service before
# being written as an assertion.

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def details(client, **payload):
    return client.post("/tools/details", json=payload)


def test_market_id_is_required_at_the_http_layer(client):
    response = client.post("/tools/details", json={"product_id": "prod_000"})
    assert response.status_code == 422


def test_direct_hit_in_the_requested_market_resolves_immediately(client):
    response = details(client, market_id="us", product_id="prod_000")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["product"]["id"] == "prod_000"
    assert body["product"]["market_id"] == "us"
    assert body["product"]["price"] == 52.18
    assert body["product"]["currency"] == "USD"
    assert body["unresolved_reason"] is None


def test_cross_market_redirect_us_id_requested_under_fr(client):
    # Requesting the US id "prod_000" while scoped to market_id="fr" must
    # seamlessly resolve to the FR sibling via product_group_id, not 404.
    response = details(client, market_id="fr", product_id="prod_000")
    body = response.json()
    assert body["resolved"] is True
    assert body["product"]["id"] == "prod_000_fr"
    assert body["product"]["market_id"] == "fr"
    assert body["product"]["price"] == 48.0
    assert body["product"]["currency"] == "EUR"


def test_cross_market_redirect_works_from_any_sibling_id(client):
    # Passing the FR-specific id while scoped to market_id="de" must still
    # resolve via the shared product_group_id, not just from the "canonical" id.
    response = details(client, market_id="de", product_id="prod_000_fr")
    body = response.json()
    assert body["resolved"] is True
    assert body["product"]["id"] == "prod_000_de"
    assert body["product"]["market_id"] == "de"


def test_localized_variants_list_excludes_the_resolved_market_itself(client):
    response = details(client, market_id="us", product_id="prod_000")
    body = response.json()
    variant_markets = {v["market_id"] for v in body["localized_variants"]}
    assert variant_markets == {"fr", "de", "uk"}
    assert "us" not in variant_markets


def test_localized_variants_carry_independent_prices_never_fx_converted(client):
    response = details(client, market_id="us", product_id="prod_000")
    variants_by_market = {v["market_id"]: v for v in response.json()["localized_variants"]}
    assert variants_by_market["fr"]["price"] == 48.0
    assert variants_by_market["fr"]["currency"] == "EUR"
    assert variants_by_market["de"]["price"] == 48.0
    assert variants_by_market["de"]["currency"] == "EUR"
    assert variants_by_market["uk"]["price"] == 41.0
    assert variants_by_market["uk"]["currency"] == "GBP"


def test_product_with_no_localized_siblings_has_an_empty_variant_list(client):
    response = details(client, market_id="us", product_id="prod_003")
    body = response.json()
    assert body["resolved"] is True
    assert body["localized_variants"] == []


def test_unresolved_when_no_sibling_exists_for_the_requested_market(client):
    # prod_003 only ever exists in "us" - requesting it under "fr" must fail
    # cleanly, not redirect to an unrelated product.
    response = details(client, market_id="fr", product_id="prod_003")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["product"] is None
    assert body["localized_variants"] == []
    assert body["unresolved_reason"] == "Product 'prod_003' is not available in market 'fr'."


def test_unresolved_for_a_market_that_does_not_exist_at_all(client):
    response = details(client, market_id="jp", product_id="prod_000")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["unresolved_reason"] == "Product 'prod_000' is not available in market 'jp'."


def test_unresolved_for_a_completely_unknown_id_never_errors(client):
    response = details(client, market_id="us", product_id="does-not-exist")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["unresolved_reason"] == "Product 'does-not-exist' is not available in market 'us'."


def test_non_product_id_is_rejected_with_a_clear_reason_not_a_crash(client):
    # bundle_001 is a real, valid id - just not a *product* - this endpoint
    # is product-detail-specific (bundle/collection resolution is Task 12).
    response = details(client, market_id="us", product_id="bundle_001")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["unresolved_reason"] == "'bundle_001' refers to a bundle, not a product."


def test_echoes_requested_product_id_and_market_id_regardless_of_resolution(client):
    response = details(client, market_id="fr", product_id="prod_000")
    body = response.json()
    assert body["requested_product_id"] == "prod_000"
    assert body["market_id"] == "fr"