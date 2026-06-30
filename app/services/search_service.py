# Search tool: core filtering (CLAUDE.md S3.3, S5.2).
#
# Scope note: this is the structured-filter core only (market/category/tags/
# price/in_stock_only + deterministic sort). Free-text relevance ranking for
# `query` (RapidFuzz) and the duplicate-name advisory are Task 10's job -
# `query` is accepted on the request schema but intentionally has no effect
# yet, so this task doesn't silently half-implement Task 10's scope.
#
# Deliberate divergence from a literal `stock_qty > 0` in_stock_only check:
# CLAUDE.md S3.3 forbids deriving availability from stock_qty anywhere in
# this codebase, and is_purchasable() (Task 6) is the single named authority
# for "can this be sold right now". Using stock_qty > 0 here would wrongly
# exclude prod_stock_001 (stock 0, available True - a legitimate backorder)
# and wrongly include prod_stock_002 (stock 14, available False - on hold).
# in_stock_only therefore filters through is_purchasable(), matching what
# SearchCatalogRequest.in_stock_only's own Field description already says.

from typing import Any, List

from app.indexing.catalog_index import CatalogIndex
from app.models.entities import PriceState
from app.models.tool_io import SearchCatalogRequest, SearchCatalogResponse, SearchResultItem
from app.services.pricing_policy import is_purchasable

_SEARCHABLE_TYPES = ("product", "gift_card", "bundle")


def _matches(entity: Any, request: SearchCatalogRequest) -> bool:
    if entity.market_id != request.market_id:
        return False
    if entity.type not in _SEARCHABLE_TYPES:
        return False
    if request.category is not None and entity.category != request.category:
        return False
    if request.tags:
        entity_tags = set(getattr(entity, "tags", None) or [])
        if not entity_tags.intersection(request.tags):
            return False
    price = getattr(entity, "price", None)
    if request.min_price is not None and (price is None or price < request.min_price):
        return False
    if request.max_price is not None and (price is None or price > request.max_price):
        return False
    if request.in_stock_only and not is_purchasable(entity):
        return False
    return True


def _price_sort_key(entity: Any, *, descending: bool):
    price = getattr(entity, "price", None)
    if price is None:
        # Unpriced items (NULL/MISSING price_state) sort last regardless of direction.
        return (True, 0.0)
    return (False, -price if descending else price)


def _rating_desc_sort_key(entity: Any):
    rating = getattr(entity, "rating", None)
    if rating is None:
        return (True, 0.0)
    return (False, -rating)


def _sort_matches(entities: List[Any], sort_by: str) -> List[Any]:
    if sort_by == "price_asc":
        return sorted(entities, key=lambda e: _price_sort_key(e, descending=False))
    if sort_by == "price_desc":
        return sorted(entities, key=lambda e: _price_sort_key(e, descending=True))
    if sort_by == "rating_desc":
        return sorted(entities, key=_rating_desc_sort_key)
    # "relevance": no scoring model yet (Task 10) - preserve stable catalog order.
    return entities


def _to_search_result_item(entity: Any) -> SearchResultItem:
    price_state: PriceState = entity.price_state
    return SearchResultItem(
        id=entity.id,
        type=entity.type,
        name=entity.name,
        category=entity.category,
        price=entity.price,
        currency=getattr(entity, "currency", None),
        price_state=price_state.value,
        is_purchasable=is_purchasable(entity),
        rating=getattr(entity, "rating", None),
        review_count=getattr(entity, "review_count", None),
        tags=getattr(entity, "tags", None),
        possible_duplicate_ids=None,
    )


def search_catalog(request: SearchCatalogRequest, index: CatalogIndex) -> SearchCatalogResponse:
    """Filter + sort the catalog for one market. O(n) over the index; the
    catalog is small enough that this beats maintaining extra composite
    indices for marginal gain (CLAUDE.md: no over-engineering)."""
    matches = [entity for entity in index.by_id.values() if _matches(entity, request)]
    matches = _sort_matches(matches, request.sort_by)

    total_matches = len(matches)
    sliced = matches[: request.limit]
    results = [_to_search_result_item(entity) for entity in sliced]

    return SearchCatalogResponse(
        market_id=request.market_id,
        total_matches=total_matches,
        results=results,
    )
