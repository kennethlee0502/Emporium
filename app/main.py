# FastAPI app entrypoint (CLAUDE.md S2.1).
#
# lifespan runs the full ingestion pipeline (load -> repair -> sanitize ->
# validate -> quarantine) and builds the read-only index exactly once, at
# startup. The result is stored on app.state, not a module-level mutable
# global, so every request reads the same immutable, already-built index -
# no per-request parsing or sanitization (that already happened here).
#
# App-level description/tags exist for one reason: this OpenAPI document
# IS the function-calling contract an upstream LLM agent reads. "tools" is
# the agent-facing surface (versioned under /v1, see app/routers/tools.py);
# "ops" is the operator/infrastructure surface and is intentionally kept
# out of the agent's mental model of what it can call.

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import CATALOG_PATH
from app.indexing.catalog_index import build_catalog_index
from app.ingestion.loader import load_catalog_from_file
from app.routers.tools import router as tools_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    result = load_catalog_from_file(CATALOG_PATH)
    app.state.catalog_index = build_catalog_index(result.valid_records)
    app.state.anomaly_report = result.report
    yield


app = FastAPI(
    title="Emporium Product Tool Service",
    description=(
        "Stateless function-calling tool layer for an upstream AI Shopping "
        "Agent - not a human-facing API. Every tool under /v1/tools requires "
        "an explicit market_id and returns structured, agent-readable JSON; "
        "no tool ever returns raw HTML or unsanitized catalog text. There is "
        "no session, cart, or order state held server-side - each call is a "
        "pure function of its request body plus the read-only catalog index "
        "built once at startup. A market gap, an unpurchasable item, or an "
        "unresolved reference is always reported as structured data "
        "(resolved=false / status=... / rejected_items=...), never as an "
        "HTTP error - so the calling agent can reason about partial results "
        "without needing exception-handling logic of its own."
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "tools",
            "description": (
                "Function-calling tools for the upstream AI Shopping Agent: "
                "search_catalog, get_product_details, resolve_bundle, "
                "resolve_collection, calculate_cart."
            ),
        },
        {
            "name": "ops",
            "description": "Operator/infrastructure endpoints. Not part of the agent's tool surface.",
        },
    ],
)
app.include_router(tools_router)


@app.get(
    "/health",
    tags=["ops"],
    summary="Service + catalog ingestion health",
    operation_id="health_check",
)
def health() -> JSONResponse:
    """Report whether the catalog ingested successfully at startup, plus the
    full anomaly report (valid/quarantined counts, price coercions,
    price-state breakdown, injection-flagged count). Returns 503 if the
    index never populated."""
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
