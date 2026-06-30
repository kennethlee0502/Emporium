# FastAPI app entrypoint (CLAUDE.md S2.1).
#
# lifespan runs the full ingestion pipeline (load -> repair -> sanitize ->
# validate -> quarantine) and builds the read-only index exactly once, at
# startup. The result is stored on app.state, not a module-level mutable
# global, so every request reads the same immutable, already-built index -
# no per-request parsing or sanitization (that already happened here).

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import CATALOG_PATH
from app.indexing.catalog_index import build_catalog_index
from app.ingestion.loader import load_catalog_from_file


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    result = load_catalog_from_file(CATALOG_PATH)
    app.state.catalog_index = build_catalog_index(result.valid_records)
    app.state.anomaly_report = result.report
    yield


app = FastAPI(title="Emporium Product Tool Service", lifespan=lifespan)


@app.get("/health")
def health() -> JSONResponse:
    index = getattr(app.state, "catalog_index", None)
    report = getattr(app.state, "anomaly_report", None)
    indexed_count = len(index.by_id) if index is not None else 0
    is_ready = indexed_count > 0

    payload = {
        "status": "ok" if is_ready else "not_ready",
        "indexed_count": indexed_count,
        "anomaly_report": {
            "total_records": report.total_records if report else 0,
            "total_valid": report.total_valid if report else 0,
            "total_quarantined": report.total_quarantined if report else 0,
            "price_coercions_executed": report.price_coercions_executed if report else 0,
            "price_state_counts": report.price_state_counts if report else {},
            "injection_flagged_count": report.injection_flagged_count if report else 0,
        },
    }

    return JSONResponse(status_code=200 if is_ready else 503, content=payload)
