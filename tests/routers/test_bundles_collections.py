# resolve_bundle / resolve_collection regression tests (CLAUDE.md S3.4, S5.2, S7).
# Integration tests through the real HTTP routes (POST /v1/tools/bundle,
# POST /v1/tools/collection), against the real ingested catalog.json - every
# id/price/status below was read out of the live resolution service before
# being written as an assertion.

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.indexing.catalog_index import build_catalog_index
from app.ingestion.loader import load_catalog_from_file
from app.services.resolution_service import resolve_collection_member_status


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def index():
    result = load_catalog_from_file("catalog.json")
    return build_catalog_index(result.valid_records)


def bundle_req(client, **payload):
    return client.post("/v1/tools/bundle", json=payload)


def collection_req(client, **payload):
    return client.post("/v1/tools/collection", json=payload)


# --- resolve_bundle ---


def test_bundle_market_id_is_required_at_the_http_layer(client):
    response = client.post("/v1/tools/bundle", json={"bundle_id": "bundle_001"})
    assert response.status_code == 422


def test_bundle_resolves_with_partial_component_breakdown(client):
    response = bundle_req(client, market_id="us", bundle_id="bundle_001")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["name"] == "Capsule Starter Set"
    assert body["price"] == 199.0

    components = {c["id"]: c for c in body["components"]}
    assert components.keys() == {"prod_000", "prod_005", "prod_018"}
    assert components["prod_000"]["status"] == "unavailable"
    assert components["prod_005"]["status"] == "active"
    assert components["prod_018"]["status"] == "active"


def test_bundle_purchasability_is_independent_of_component_status(client):
    # bundle_001 is available=True even though prod_000 (a member) is not
    # purchasable - CLAUDE.md S7: bundle availability is independently
    # authored and must never be derived from / overridden by member status.
    response = bundle_req(client, market_id="us", bundle_id="bundle_001")
    body = response.json()
    assert body["bundle_is_purchasable"] is True
    assert body["all_components_active"] is False  # prod_000 drags this down, but NOT bundle_is_purchasable


def test_bundle_request_under_the_wrong_market_does_not_resolve(client):
    response = bundle_req(client, market_id="fr", bundle_id="bundle_001")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["components"] == []
    assert body["unresolved_reason"] == "Bundle 'bundle_001' is not available in market 'fr'."


def test_unknown_bundle_id_never_errors(client):
    response = bundle_req(client, market_id="us", bundle_id="does-not-exist")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["unresolved_reason"] == "Bundle 'does-not-exist' was not found."


def test_non_bundle_id_is_rejected_with_a_clear_reason(client):
    response = bundle_req(client, market_id="us", bundle_id="prod_000")
    body = response.json()
    assert body["resolved"] is False
    assert body["unresolved_reason"] == "'prod_000' refers to a product, not a bundle."


# --- resolve_collection ---


def test_collection_market_id_is_required_at_the_http_layer(client):
    response = client.post("/v1/tools/collection", json={"collection_id": "coll_001"})
    assert response.status_code == 422


def test_collection_surfaces_cross_market_integrity_status_per_member(client):
    response = collection_req(client, market_id="us", collection_id="coll_001")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["name"] == "Summer Essentials"

    components = {c["id"]: c for c in body["components"]}
    assert components.keys() == {"prod_000", "prod_004", "prod_eur_002"}

    # prod_000: resolved in us market, but not purchasable right now.
    assert components["prod_000"]["status"] == "unavailable"
    assert components["prod_000"]["is_purchasable"] is False

    # prod_004: resolved in us market and purchasable.
    assert components["prod_004"]["status"] == "active"
    assert components["prod_004"]["is_purchasable"] is True

    # prod_eur_002: a real product, but fr-only - listed inside a us
    # collection, so it is out of scope for a us-market request, not "not found".
    assert components["prod_eur_002"]["status"] == "out_of_scope"
    assert components["prod_eur_002"]["name"] is None
    assert components["prod_eur_002"]["price"] is None

    assert body["active_component_count"] == 1


def test_collection_request_under_the_wrong_market_does_not_resolve(client):
    response = collection_req(client, market_id="fr", collection_id="coll_001")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["components"] == []
    assert body["unresolved_reason"] == "Collection 'coll_001' is not available in market 'fr'."


def test_unknown_collection_id_never_errors(client):
    response = collection_req(client, market_id="us", collection_id="does-not-exist")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["unresolved_reason"] == "Collection 'does-not-exist' was not found."


def test_non_collection_id_is_rejected_with_a_clear_reason(client):
    response = collection_req(client, market_id="us", collection_id="bundle_001")
    body = response.json()
    assert body["resolved"] is False
    assert body["unresolved_reason"] == "'bundle_001' refers to a bundle, not a collection."


def test_collection_member_with_no_real_entity_anywhere_is_not_found(index):
    # No real catalog record has a broken/unknown member_id, so this branch
    # is proven directly against the resolution service rather than through
    # a real collection's HTTP response (CLAUDE.md S5.2 still applies: this
    # must resolve gracefully, never raise).
    status = resolve_collection_member_status("totally-fake-id-xyz", "us", index)
    assert status.status == "not_found"
    assert status.name is None
    assert status.is_purchasable is False