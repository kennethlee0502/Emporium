# Purchasability rules (CLAUDE.md S3.3, S5.3).
#
# is_purchasable() is the single named authority for "can this be sold right
# now" - every other service (search, cart calculation) must call this
# rather than re-deriving the conjunction inline. `available` is never
# inferred from `stock_qty`; they are independent commercial fields, and a
# contradiction between them (CLAUDE.md S7: prod_stock_001, prod_stock_002)
# is resolved by trusting `available` as the authority, not by recomputing
# it from stock count.

from app.models.entities import Bundle, CatalogEntity, GiftCard, PriceState, Product


def is_purchasable(entity: CatalogEntity) -> bool:
    """True if `entity` can be sold right now, given its own declared state."""
    if isinstance(entity, (Product, Bundle)):
        return entity.available and entity.price_state is PriceState.NORMAL

    if isinstance(entity, GiftCard):
        # Gift cards are denomination-priced, not fixed-priced, so their
        # price_state is intentionally NULL (CLAUDE.md S3.2) - `available`
        # alone governs whether they can be sold.
        return entity.available

    # Collection and Page (and any future non-commerce type) have no
    # independent price/stock authority of their own and are never directly
    # purchasable.
    return False
