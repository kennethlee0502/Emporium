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
    CalculateCartRequest,
    CalculateCartResponse,
    GetProductDetailsRequest,
    GetProductDetailsResponse,
    ResolveBundleRequest,
    ResolveBundleResponse,
    ResolveCollectionRequest,
    ResolveCollectionResponse,
    SearchCatalogRequest,
    SearchCatalogResponse,
)
from app.services.cart_calculation_service import calculate_cart
from app.services.resolution_service import resolve_bundle, resolve_collection, resolve_product_details
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


@router.post("/bundle", response_model=ResolveBundleResponse)
def bundle(payload: ResolveBundleRequest, request: Request) -> ResolveBundleResponse:
    index = request.app.state.catalog_index
    return resolve_bundle(payload, index)


@router.post("/collection", response_model=ResolveCollectionResponse)
def collection(payload: ResolveCollectionRequest, request: Request) -> ResolveCollectionResponse:
    index = request.app.state.catalog_index
    return resolve_collection(payload, index)


@router.post("/cart", response_model=CalculateCartResponse)
def cart(payload: CalculateCartRequest, request: Request) -> CalculateCartResponse:
    index = request.app.state.catalog_index
    return calculate_cart(payload, index)
