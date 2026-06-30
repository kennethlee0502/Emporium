# One route per agent-facing tool (CLAUDE.md S2.3).
#
# POST, not GET: SearchCatalogRequest has nested/list fields (tags,
# line_items elsewhere) that don't map cleanly onto query-string encoding,
# and the function-calling contract is the JSON request body Pydantic
# model itself - POST + JSON body is the natural shape for that.
#
# Routes are thin by design: parse the validated request, pull the
# already-built read-only index off app.state, delegate to the service.

from fastapi import APIRouter, Request

from app.models.tool_io import (
    GetProductDetailsRequest,
    GetProductDetailsResponse,
    SearchCatalogRequest,
    SearchCatalogResponse,
)
from app.services.resolution_service import resolve_product_details
from app.services.search_service import search_catalog

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/search", response_model=SearchCatalogResponse)
def search(payload: SearchCatalogRequest, request: Request) -> SearchCatalogResponse:
    index = request.app.state.catalog_index
    return search_catalog(payload, index)


@router.post("/details", response_model=GetProductDetailsResponse)
def details(payload: GetProductDetailsRequest, request: Request) -> GetProductDetailsResponse:
    index = request.app.state.catalog_index
    return resolve_product_details(payload, index)
