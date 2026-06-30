# Product detail lookup, cross-market variant resolution, and bundle/
# collection partial resolution (CLAUDE.md S1.9, S3.4, S5.2, S7).
#
# Resolution order for a (product_id, market_id) request (resolve_product_details):
#   1. Exact id match in the index, already in the requested market -> done.
#   2. Exact id match exists but in a *different* market (e.g. a "fr" id
#      requested under market_id="us") -> follow its product_group_id and
#      look for a sibling in the requested market.
#   3. No direct id match at all -> treat product_id itself as a
#      product_group_id and look for a sibling in the requested market.
#   4. Nothing found -> resolved=False with an explicit unresolved_reason.
#      This never raises and never 404s/500s - CLAUDE.md S5.2: a market gap
#      is a normal, expected outcome, not an error.
#
# Bundle and collection resolution (resolve_bundle / resolve_collection)
# never let one bad/unavailable member fail the whole call - CLAUDE.md S5.2:
# "When a member_ids reference doesn't resolve in the requested market,
# return it as an explicit 'unresolved' entry - do not throw." A bundle's
# own purchasability is independently authored and is never derived from
# its components' status (CLAUDE.md S7, bundle_001).

from typing import Optional, Tuple

from app.indexing.catalog_index import CatalogIndex
from app.models.entities import Bundle, Collection, Product
from app.models.tool_io import (
    BundleComponentStatus,
    CollectionComponentStatus,
    GetProductDetailsRequest,
    GetProductDetailsResponse,
    LocalizedVariantSummary,
    ProductDetail,
    ResolveBundleRequest,
    ResolveBundleResponse,
    ResolveCollectionRequest,
    ResolveCollectionResponse,
)
from app.services.pricing_policy import is_purchasable


def _resolve_product(
    product_id: str, market_id: str, index: CatalogIndex
) -> Tuple[Optional[Product], Optional[str]]:
    direct = index.get_by_id(product_id)

    if isinstance(direct, Product) and direct.market_id == market_id:
        return direct, None

    if direct is not None and not isinstance(direct, Product):
        return None, f"'{product_id}' refers to a {direct.type}, not a product."

    group_id = direct.product_group_id if isinstance(direct, Product) else product_id
    sibling = index.get_group_siblings(group_id).get(market_id)
    if isinstance(sibling, Product):
        return sibling, None

    return None, f"Product '{product_id}' is not available in market '{market_id}'."


def _to_product_detail(entity: Product) -> ProductDetail:
    return ProductDetail(
        id=entity.id,
        product_group_id=entity.product_group_id,
        market_id=entity.market_id,
        name=entity.name,
        category=entity.category,
        description=entity.description,
        price=entity.price,
        currency=entity.currency,
        price_state=entity.price_state.value,
        is_purchasable=is_purchasable(entity),
        stock_qty=entity.stock_qty,
        available=entity.available,
        rating=entity.rating,
        review_count=entity.review_count,
        tags=entity.tags,
    )


def _to_localized_variant_summary(entity: Product) -> LocalizedVariantSummary:
    return LocalizedVariantSummary(
        id=entity.id,
        market_id=entity.market_id,
        name=entity.name,
        price=entity.price,
        currency=entity.currency,
        price_state=entity.price_state.value,
        is_purchasable=is_purchasable(entity),
    )


def resolve_product_details(
    request: GetProductDetailsRequest, index: CatalogIndex
) -> GetProductDetailsResponse:
    resolved_entity, unresolved_reason = _resolve_product(request.product_id, request.market_id, index)

    if resolved_entity is None:
        return GetProductDetailsResponse(
            requested_product_id=request.product_id,
            market_id=request.market_id,
            resolved=False,
            product=None,
            localized_variants=[],
            unresolved_reason=unresolved_reason,
        )

    siblings = index.get_group_siblings(resolved_entity.product_group_id)
    localized_variants = [
        _to_localized_variant_summary(sibling)
        for sibling_market_id, sibling in siblings.items()
        if sibling_market_id != resolved_entity.market_id
    ]

    return GetProductDetailsResponse(
        requested_product_id=request.product_id,
        market_id=request.market_id,
        resolved=True,
        product=_to_product_detail(resolved_entity),
        localized_variants=localized_variants,
        unresolved_reason=None,
    )


# ---------------------------------------------------------------------------
# resolve_bundle
# ---------------------------------------------------------------------------


def _resolve_bundle_entity(
    bundle_id: str, market_id: str, index: CatalogIndex
) -> Tuple[Optional[Bundle], Optional[str]]:
    entity = index.get_by_id(bundle_id)
    if entity is None:
        return None, f"Bundle '{bundle_id}' was not found."
    if not isinstance(entity, Bundle):
        return None, f"'{bundle_id}' refers to a {entity.type}, not a bundle."
    if entity.market_id != market_id:
        return None, f"Bundle '{bundle_id}' is not available in market '{market_id}'."
    return entity, None


def _to_bundle_component_status(member_id: str, index: CatalogIndex) -> BundleComponentStatus:
    entity = index.get_by_id(member_id)
    if not isinstance(entity, Product):
        return BundleComponentStatus(
            id=member_id, name=None, status="not_found", price=None, currency=None, is_purchasable=False
        )
    purchasable = is_purchasable(entity)
    return BundleComponentStatus(
        id=member_id,
        name=entity.name,
        status="active" if purchasable else "unavailable",
        price=entity.price,
        currency=entity.currency,
        is_purchasable=purchasable,
    )


def resolve_bundle(request: ResolveBundleRequest, index: CatalogIndex) -> ResolveBundleResponse:
    bundle_entity, unresolved_reason = _resolve_bundle_entity(request.bundle_id, request.market_id, index)

    if bundle_entity is None:
        return ResolveBundleResponse(
            requested_bundle_id=request.bundle_id,
            market_id=request.market_id,
            resolved=False,
            components=[],
            all_components_active=False,
            unresolved_reason=unresolved_reason,
        )

    components = [_to_bundle_component_status(member_id, index) for member_id in bundle_entity.member_ids]
    all_components_active = bool(components) and all(c.status == "active" for c in components)

    return ResolveBundleResponse(
        requested_bundle_id=request.bundle_id,
        market_id=request.market_id,
        resolved=True,
        name=bundle_entity.name,
        price=bundle_entity.price,
        currency=bundle_entity.currency,
        price_state=bundle_entity.price_state.value,
        # Independently authored - never derived from `components` above (CLAUDE.md S7).
        bundle_is_purchasable=is_purchasable(bundle_entity),
        components=components,
        all_components_active=all_components_active,
        unresolved_reason=None,
    )


# ---------------------------------------------------------------------------
# resolve_collection
# ---------------------------------------------------------------------------


def _resolve_collection_entity(
    collection_id: str, market_id: str, index: CatalogIndex
) -> Tuple[Optional[Collection], Optional[str]]:
    entity = index.get_by_id(collection_id)
    if entity is None:
        return None, f"Collection '{collection_id}' was not found."
    if not isinstance(entity, Collection):
        return None, f"'{collection_id}' refers to a {entity.type}, not a collection."
    if entity.market_id != market_id:
        return None, f"Collection '{collection_id}' is not available in market '{market_id}'."
    return entity, None


def _entity_exists_in_any_market(entity_id: str, index: CatalogIndex) -> bool:
    """True if `entity_id` resolves to something *somewhere* in the catalog,
    even if not in the market currently being checked - distinguishes
    'out_of_scope' (real product, wrong market) from 'not_found' (unknown id)."""
    if index.get_by_id(entity_id) is not None:
        return True
    return bool(index.get_group_siblings(entity_id))


def resolve_collection_member_status(
    member_id: str, market_id: str, index: CatalogIndex
) -> CollectionComponentStatus:
    # Reuses the same multi-hop product resolution as get_product_details
    # (direct id+market hit, then product_group_id fallback) - a collection
    # member is just a product reference, so the same redirection rules apply.
    resolved_entity, _ = _resolve_product(member_id, market_id, index)
    if resolved_entity is not None:
        purchasable = is_purchasable(resolved_entity)
        return CollectionComponentStatus(
            id=member_id,
            name=resolved_entity.name,
            status="active" if purchasable else "unavailable",
            price=resolved_entity.price,
            currency=resolved_entity.currency,
            is_purchasable=purchasable,
        )

    status = "out_of_scope" if _entity_exists_in_any_market(member_id, index) else "not_found"
    return CollectionComponentStatus(
        id=member_id, name=None, status=status, price=None, currency=None, is_purchasable=False
    )


def resolve_collection(request: ResolveCollectionRequest, index: CatalogIndex) -> ResolveCollectionResponse:
    collection_entity, unresolved_reason = _resolve_collection_entity(
        request.collection_id, request.market_id, index
    )

    if collection_entity is None:
        return ResolveCollectionResponse(
            requested_collection_id=request.collection_id,
            market_id=request.market_id,
            resolved=False,
            components=[],
            active_component_count=0,
            unresolved_reason=unresolved_reason,
        )

    components = [
        resolve_collection_member_status(member_id, request.market_id, index)
        for member_id in collection_entity.member_ids
    ]
    active_component_count = sum(1 for c in components if c.status == "active")

    return ResolveCollectionResponse(
        requested_collection_id=request.collection_id,
        market_id=request.market_id,
        resolved=True,
        name=collection_entity.name,
        components=components,
        active_component_count=active_component_count,
        unresolved_reason=None,
    )
