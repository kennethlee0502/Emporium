# Product detail lookup + cross-market variant resolution (CLAUDE.md S1.9, S5.2).
#
# Resolution order for a (product_id, market_id) request:
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
# Bundle/collection member resolution (Task 12) is a separate concern and
# does not belong in this function.

from typing import Optional, Tuple

from app.indexing.catalog_index import CatalogIndex
from app.models.entities import Product
from app.models.tool_io import (
    GetProductDetailsRequest,
    GetProductDetailsResponse,
    LocalizedVariantSummary,
    ProductDetail,
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
