# calculate_cart regression tests (CLAUDE.md S1, S3.3, S5.4).
# Integration tests through the real HTTP route (POST /v1/tools/cart),
# against the real ingested catalog.json - every price/reason below was
# read out of the live cart service before being written as an assertion.

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def cart(client, market_id="us", line_items=None):
    return client.post(
        "/v1/tools/cart", json={"market_id": market_id, "line_items": line_items or []}
    )


def test_market_id_is_required_at_the_http_layer(client):
    response = client.post("/v1/tools/cart", json={"line_items": [{"product_id": "prod_001", "quantity": 1}]})
    assert response.status_code == 422


def test_empty_line_items_is_rejected_at_the_schema_layer(client):
    response = client.post("/v1/tools/cart", json={"market_id": "us", "line_items": []})
    assert response.status_code == 422


def test_happy_path_prices_product_and_bundle_correctly(client):
    response = cart(
        client,
        line_items=[
            {"product_id": "prod_001", "quantity": 2},
            {"product_id": "bundle_001", "quantity": 1},
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rejected_items"] == []
    assert body["currency"] == "USD"
    assert body["subtotal"] == 278.4

    by_id = {li["product_id"]: li for li in body["line_items"]}
    assert by_id["prod_001"]["unit_price"] == 39.7
    assert by_id["prod_001"]["line_total"] == 79.4
    assert by_id["bundle_001"]["unit_price"] == 199.0
    assert by_id["bundle_001"]["line_total"] == 199.0


def test_unavailable_product_is_rejected_with_a_clear_reason(client):
    # prod_stock_002: stock 14 but available=False - on hold, not purchasable.
    response = cart(client, line_items=[{"product_id": "prod_stock_002", "quantity": 1}])
    body = response.json()
    assert body["line_items"] == []
    assert len(body["rejected_items"]) == 1
    assert body["rejected_items"][0]["product_id"] == "prod_stock_002"
    assert "unavailable" in body["rejected_items"][0]["reason"]


def test_null_price_product_is_rejected_with_a_price_specific_reason(client):
    # prod_null_001: made-to-order, price intentionally null - cannot be
    # priced through the standard cart path.
    response = cart(client, line_items=[{"product_id": "prod_null_001", "quantity": 1}])
    body = response.json()
    assert body["line_items"] == []
    reason = body["rejected_items"][0]["reason"]
    assert "valid fixed price" in reason


def test_gift_card_with_valid_denomination_prices_correctly(client):
    response = cart(
        client, line_items=[{"product_id": "gift_001", "quantity": 1, "gift_card_denomination": 50}]
    )
    body = response.json()
    assert body["rejected_items"] == []
    assert body["line_items"][0]["unit_price"] == 50.0
    assert body["line_items"][0]["line_total"] == 50.0
    assert body["currency"] == "USD"


def test_gift_card_without_denomination_is_rejected(client):
    response = cart(client, line_items=[{"product_id": "gift_001", "quantity": 1}])
    body = response.json()
    assert body["line_items"] == []
    assert "requires a gift_card_denomination" in body["rejected_items"][0]["reason"]


def test_gift_card_with_invalid_denomination_is_rejected(client):
    response = cart(
        client, line_items=[{"product_id": "gift_001", "quantity": 1, "gift_card_denomination": 999}]
    )
    body = response.json()
    assert body["line_items"] == []
    reason = body["rejected_items"][0]["reason"]
    assert "not a valid denomination" in reason
    assert "25" in reason and "50" in reason and "100" in reason and "250" in reason


def test_non_priceable_entity_type_is_rejected(client):
    # coll_001 is a collection, not something that can be added to a cart.
    response = cart(client, line_items=[{"product_id": "coll_001", "quantity": 1}])
    body = response.json()
    assert body["line_items"] == []
    assert "refers to a collection" in body["rejected_items"][0]["reason"]


def test_unknown_product_id_is_rejected_not_an_error(client):
    response = cart(client, line_items=[{"product_id": "does-not-exist", "quantity": 1}])
    assert response.status_code == 200
    body = response.json()
    assert body["line_items"] == []
    assert "was not found" in body["rejected_items"][0]["reason"]


def test_wrong_market_id_is_rejected_never_silently_redirected(client):
    # prod_000_fr exists, but only in market "fr" - under market_id="us" it
    # must be rejected, never silently substituted for prod_000.
    response = cart(client, market_id="us", line_items=[{"product_id": "prod_000_fr", "quantity": 1}])
    body = response.json()
    assert body["line_items"] == []
    reason = body["rejected_items"][0]["reason"]
    assert "not available in market 'us'" in reason


def test_mixed_valid_and_invalid_line_items_isolate_correctly(client):
    response = cart(
        client,
        line_items=[
            {"product_id": "prod_001", "quantity": 1},
            {"product_id": "prod_stock_002", "quantity": 3},
            {"product_id": "does-not-exist", "quantity": 1},
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["line_items"]) == 1
    assert body["line_items"][0]["product_id"] == "prod_001"
    assert body["subtotal"] == 39.7
    assert len(body["rejected_items"]) == 2
    rejected_ids = {r["product_id"] for r in body["rejected_items"]}
    assert rejected_ids == {"prod_stock_002", "does-not-exist"}


def test_cart_with_everything_rejected_has_null_currency_and_zero_subtotal(client):
    response = cart(client, line_items=[{"product_id": "does-not-exist", "quantity": 1}])
    body = response.json()
    assert body["line_items"] == []
    assert body["currency"] is None
    assert body["subtotal"] == 0.0


def test_no_persistence_two_identical_calls_return_identical_results(client):
    payload = [{"product_id": "prod_001", "quantity": 2}]
    first = cart(client, line_items=payload).json()
    second = cart(client, line_items=payload).json()
    assert first == second