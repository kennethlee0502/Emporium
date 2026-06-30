# Stateless cart/price calculation (CLAUDE.md S1, S3.3, S5.4).
#
# No session, no persisted cart, no database lookup beyond the read-only
# index - every call is a pure function of the request. Each line item is
# priced or rejected independently; one bad line item never fails the whole
# request (CLAUDE.md S5.2's "partial-resolution, never throw" principle,
# applied here to cart pricing rather than bundle/collection resolution).
#
# is_purchasable() (Task 6) remains the single authority for "can this be
# sold" - it is never re-derived inline here. Where this module branches on
# `entity.available` / `entity.price_state` directly, that is only to craft
# a more specific rejection *message*, never to make the accept/reject
# decision itself.
#
# Deliberate divergence from get_product_details' cross-market redirection
# (Task 11): a cart line item's product_id must match the requested
# market_id exactly. An id that only exists in a different market is
# rejected, never silently substituted for a different-market variant with
# a different price - CLAUDE.md S5.2: "items only available in a different
# market are rejected, never silently re-priced."

from typing import List, Optional, Tuple

from app.indexing.catalog_index import CatalogIndex
from app.models.entities import Bundle, GiftCard, Product
from app.models.tool_io import (
    CalculateCartRequest,
    CalculateCartResponse,
    CartLineItem,
    CartLineItemResult,
    RejectedLineItem,
)
from app.services.pricing_policy import is_purchasable


def _reject(line_item: CartLineItem, reason: str) -> RejectedLineItem:
    return RejectedLineItem(product_id=line_item.product_id, quantity=line_item.quantity, reason=reason)


def _price_gift_card_line(
    entity: GiftCard, line_item: CartLineItem
) -> Tuple[Optional[CartLineItemResult], Optional[RejectedLineItem]]:
    if not is_purchasable(entity):
        return None, _reject(line_item, f"'{entity.name}' is currently unavailable.")

    denomination = line_item.gift_card_denomination
    if denomination is None:
        return None, _reject(
            line_item, f"'{entity.name}' requires a gift_card_denomination to be specified."
        )
    if denomination not in entity.denominations:
        valid = ", ".join(str(d) for d in entity.denominations)
        return None, _reject(
            line_item,
            f"{denomination} is not a valid denomination for '{entity.name}'. Valid denominations: {valid}.",
        )

    result = CartLineItemResult(
        product_id=entity.id,
        name=entity.name,
        quantity=line_item.quantity,
        unit_price=denomination,
        line_total=round(denomination * line_item.quantity, 2),
        currency=entity.currency,
    )
    return result, None


def _price_standard_line(
    entity, line_item: CartLineItem
) -> Tuple[Optional[CartLineItemResult], Optional[RejectedLineItem]]:
    if not is_purchasable(entity):
        # is_purchasable() is the actual gate; this only picks the more
        # specific of its two possible failure causes for the message.
        if not entity.available:
            reason = f"'{entity.name}' is currently unavailable."
        else:
            reason = f"'{entity.name}' does not have a valid fixed price right now."
        return None, _reject(line_item, reason)

    result = CartLineItemResult(
        product_id=entity.id,
        name=entity.name,
        quantity=line_item.quantity,
        unit_price=entity.price,
        line_total=round(entity.price * line_item.quantity, 2),
        currency=entity.currency,
    )
    return result, None


def _price_line_item(
    line_item: CartLineItem, market_id: str, index: CatalogIndex
) -> Tuple[Optional[CartLineItemResult], Optional[RejectedLineItem]]:
    entity = index.get_by_id(line_item.product_id)

    if entity is None:
        return None, _reject(line_item, f"Product '{line_item.product_id}' was not found.")

    if entity.market_id != market_id:
        return None, _reject(
            line_item, f"'{line_item.product_id}' is not available in market '{market_id}'."
        )

    if isinstance(entity, GiftCard):
        return _price_gift_card_line(entity, line_item)

    if isinstance(entity, (Product, Bundle)):
        return _price_standard_line(entity, line_item)

    return None, _reject(
        line_item, f"'{line_item.product_id}' refers to a {entity.type}, which cannot be added to a cart."
    )


def calculate_cart(request: CalculateCartRequest, index: CatalogIndex) -> CalculateCartResponse:
    line_items: List[CartLineItemResult] = []
    rejected_items: List[RejectedLineItem] = []

    for line_item in request.line_items:
        priced, rejected = _price_line_item(line_item, request.market_id, index)
        if priced is not None:
            line_items.append(priced)
        else:
            rejected_items.append(rejected)

    # Safe: every successfully priced item was scoped to the single
    # requested market_id, and currency is constant within one market.
    currency = line_items[0].currency if line_items else None
    subtotal = round(sum(item.line_total for item in line_items), 2)

    return CalculateCartResponse(
        market_id=request.market_id,
        currency=currency,
        line_items=line_items,
        rejected_items=rejected_items,
        subtotal=subtotal,
    )
