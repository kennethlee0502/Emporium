# One route per agent-facing tool (CLAUDE.md S2.3, S5).
#
# POST, not GET: SearchCatalogRequest has nested/list fields (tags,
# line_items elsewhere) that don't map cleanly onto query-string encoding,
# and the function-calling contract is the JSON request body Pydantic
# model itself - POST + JSON body is the natural shape for that.
#
# Routes are thin by design: parse the validated request, pull the
# already-built read-only index off app.state, delegate to the service.
#
# Prefixed /v1: CLAUDE.md's own risk table calls for path-versioning the
# tool surface from the start, specifically so a future breaking schema
# change doesn't silently invalidate an upstream agent's cached tool
# definitions. /health is deliberately NOT under /v1 - it's an operator/
# infrastructure probe, not part of the agent-facing tool contract, and
# does not version with it.
#
# operation_id is set explicitly (rather than left to FastAPI's
# auto-generated "search_tools_search_post"-style id) to exactly match the
# tool name used throughout CLAUDE.md and this codebase's own docs/tests -
# many function-calling integrations derive the callable tool's name
# straight from operationId, so this is load-bearing, not cosmetic.

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

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.post(
    "/search",
    response_model=SearchCatalogResponse,
    operation_id="search_catalog",
    summary="Search the catalog",
)
def search(payload: SearchCatalogRequest, request: Request) -> SearchCatalogResponse:
    """Search products, gift cards, and bundles within a single market.

    Supports structured filters (category, exact-match; tags, any-match;
    min_price/max_price, inclusive; in_stock_only) and a typo-tolerant
    free-text query. Results may include a possible_duplicate_ids advisory
    for near-identical catalog entries - these are never merged, only
    flagged. Use the returned ids as product_id in get_product_details,
    calculate_cart, resolve_bundle, or resolve_collection.
    """
    index = request.app.state.catalog_index
    return search_catalog(payload, index)


@router.post(
    "/details",
    response_model=GetProductDetailsResponse,
    operation_id="get_product_details",
    summary="Get full product details, resolved to one market",
)
def details(payload: GetProductDetailsRequest, request: Request) -> GetProductDetailsResponse:
    """Resolve a single product to one market and return its full detail record.

    product_id may be an exact catalog id or a product_group_id. If the
    given id exists but in a different market than requested, it is
    automatically redirected to that market's localized sibling via
    product_group_id - the response's `product.id` may therefore differ
    from the requested product_id. If no version exists in the requested
    market, `resolved` is false with an explicit `unresolved_reason`
    (never a 404). `localized_variants` lists every other market's version
    of this same product with its own independently authored price -
    never an FX conversion of another market's price.
    """
    index = request.app.state.catalog_index
    return resolve_product_details(payload, index)


@router.post(
    "/bundle",
    response_model=ResolveBundleResponse,
    operation_id="resolve_bundle",
    summary="Resolve a bundle and the live status of its components",
)
def bundle(payload: ResolveBundleRequest, request: Request) -> ResolveBundleResponse:
    """Resolve a bundle and return an item-by-item status ledger for its components.

    Each component is reported as 'active' (purchasable now), 'unavailable'
    (exists but not currently purchasable), or 'not_found'. The bundle's
    own `bundle_is_purchasable` is independently authored and is never
    derived from component status - a bundle may remain purchasable even
    when one of its components is 'unavailable'.
    """
    index = request.app.state.catalog_index
    return resolve_bundle(payload, index)


@router.post(
    "/collection",
    response_model=ResolveCollectionResponse,
    operation_id="resolve_collection",
    summary="Resolve a collection's members against one market",
)
def collection(payload: ResolveCollectionRequest, request: Request) -> ResolveCollectionResponse:
    """Resolve a curated collection and report which of its members are
    actually live in the requested market.

    Each member is reported as 'active', 'unavailable', 'out_of_scope'
    (a real product that simply has no version in the requested market -
    e.g. a market-exclusive item listed inside another market's
    collection), or 'not_found'.
    """
    index = request.app.state.catalog_index
    return resolve_collection(payload, index)


@router.post(
    "/cart",
    response_model=CalculateCartResponse,
    operation_id="calculate_cart",
    summary="Price a set of line items - stateless, nothing persisted",
)
def cart(payload: CalculateCartRequest, request: Request) -> CalculateCartResponse:
    """Compute a price breakdown for a list of line items. Fully stateless:
    no cart is created, stored, or referenced server-side - every call is
    a pure function of the request and must include every line item the
    caller wants priced.

    Each line item is priced or rejected independently; one invalid item
    never fails the whole request. A line item whose product_id exists
    only in a different market than `market_id` is rejected outright,
    never silently re-priced against a different market's variant. Gift
    card line items must include a `gift_card_denomination` matching one
    of that card's own offered denominations.
    """
    index = request.app.state.catalog_index
    return calculate_cart(payload, index)
