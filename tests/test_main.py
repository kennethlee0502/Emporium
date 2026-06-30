# FastAPI startup + /health integration smoke test (CLAUDE.md S2.1).
#
# Uses TestClient as a context manager specifically because lifespan startup
# (and the real ingestion pipeline it runs) only fires on context-manager
# entry/exit, not on bare TestClient(app) instantiation.

import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_ready_after_real_startup_ingestion():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["indexed_count"] == 97


def test_health_echoes_the_real_anomaly_report():
    with TestClient(app) as client:
        response = client.get("/health")

    report = response.json()["anomaly_report"]
    assert report["total_records"] == 97
    assert report["total_valid"] == 97
    assert report["total_quarantined"] == 0
    assert report["price_coercions_executed"] == 2
    assert report["injection_flagged_count"] == 2
    assert report["price_state_counts"] == {
        "normal": 90,
        "null": 3,
        "missing": 1,
        "non_positive": 1,
    }


def test_catalog_index_is_populated_on_app_state_after_startup():
    with TestClient(app) as client:
        assert len(app.state.catalog_index.by_id) == 97
        assert app.state.catalog_index.get_by_id("prod_000") is not None
        assert app.state.anomaly_report.total_valid == 97
