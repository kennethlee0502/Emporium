# Search tool: core filtering + free-text relevance + duplicate advisory
# (CLAUDE.md S3.3, S3.4, S5.2).
#
# Deliberate divergence from a literal `stock_qty > 0` in_stock_only check:
# CLAUDE.md S3.3 forbids deriving availability from stock_qty anywhere in
# this codebase, and is_purchasable() (Task 6) is the single named authority
# for "can this be sold right now". Using stock_qty > 0 here would wrongly
# exclude prod_stock_001 (stock 0, available True - a legitimate backorder)
# and wrongly include prod_stock_002 (stock 14, available False - on hold).
# in_stock_only therefore filters through is_purchasable(), matching what
# SearchCatalogRequest.in_stock_only's own Field description already says.
#
# Free-text `query` matching (RapidFuzz): WRatio against a single combined
# haystack of name + description + tags. Scoring each field separately and
# taking the max was tried first and rejected: a single short tag (e.g.
# "white") independently scores ~90 via WRatio's partial-match heuristic
# regardless of the rest of the query, which let an unrelated item
# (a tee whose only relevant signal is a "white" tag) outrank the actual
# best match (a product literally named "Classic White Tee"). Combining
# fields into one haystack before scoring fixes that while still tolerating
# typos/substrings ("Crew Te" -> "...Crew Tee...", "hodie black" ->
# "...Hoodie - Black") and still scoring a genuinely unrelated query far
# lower. A query, when given, is both a filter (below-threshold candidates
# are dropped entirely) and, under sort_by == "relevance", the sort key.
#
# Duplicate advisory (CLAUDE.md S3.4): near-identical names within the
# final returned page are never merged - each item is returned independently
# with `possible_duplicate_ids` cross-referencing its siblings in that same
# page, so the calling agent can see the ambiguity rather than have it
# silently resolved on its behalf.

from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from app.indexing.catalog_index import CatalogIndex
from app.models.entities import PriceState
from app.models.tool_io import SearchCatalogRequest, SearchCatalogResponse, SearchResultItem
from app.services.pricing_policy import is_purchasable

_SEARCHABLE_TYPES = ("product", "gift_card", "bundle")

# WRatio score (0-100) below which a query match is considered noise rather
# than a genuine typo/partial hit. Empirically, against the combined
# name+description+tags haystack: real typo/substring matches in this
# catalog scored 50-90; unrelated queries scored ~34-35.
_RELEVANCE_THRESHOLD = 45.0

# fuzz.ratio (0-100) above which two names in the same result page are
# flagged as possible duplicates. Empirically: identical post-repair names
# (the prod_dupe_a/b/c family) score 100; legitimately distinct color
# variants of the same product line (e.g. "...- White" vs "...- Black")
# score ~80-83 - well clear of this threshold, so they are not flagged.
_DUPLICATE_NAME_THRESHOLD = 90.0


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


def _relevance_score(entity: Any, query: str) -> float:
    parts = [entity.name, entity.description]
    parts.extend(getattr(entity, "tags", None) or [])
    haystack = " ".join(part for part in parts if part)
    return fuzz.WRatio(query, haystack) if haystack else 0.0


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


def _sort_matches(
    entities: List[Any], sort_by: str, scores: Optional[Dict[str, float]] = None
) -> List[Any]:
    if sort_by == "price_asc":
        return sorted(entities, key=lambda e: _price_sort_key(e, descending=False))
    if sort_by == "price_desc":
        return sorted(entities, key=lambda e: _price_sort_key(e, descending=True))
    if sort_by == "rating_desc":
        return sorted(entities, key=_rating_desc_sort_key)
    if sort_by == "relevance" and scores:
        return sorted(entities, key=lambda e: -scores.get(e.id, 0.0))
    # "relevance" with no query/scores: no ranking signal - stable catalog order.
    return entities


def _find_duplicate_groups(entities: List[Any]) -> Dict[str, List[str]]:
    """Map each entity id to the ids of other entities in `entities` whose
    name is a near-identical match (CLAUDE.md S3.4: advisory only, never merged)."""
    groups: Dict[str, List[str]] = {entity.id: [] for entity in entities}
    for i, a in enumerate(entities):
        for b in entities[i + 1 :]:
            if fuzz.ratio(a.name.lower(), b.name.lower()) >= _DUPLICATE_NAME_THRESHOLD:
                groups[a.id].append(b.id)
                groups[b.id].append(a.id)
    return groups


def _to_search_result_item(entity: Any, duplicate_ids: Optional[List[str]]) -> SearchResultItem:
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
        possible_duplicate_ids=duplicate_ids or None,
    )


def search_catalog(request: SearchCatalogRequest, index: CatalogIndex) -> SearchCatalogResponse:
    """Filter + score + sort the catalog for one market. O(n) over the
    index; the catalog is small enough that this beats maintaining extra
    composite indices for marginal gain (CLAUDE.md: no over-engineering)."""
    candidates = [entity for entity in index.by_id.values() if _matches(entity, request)]

    scores: Dict[str, float] = {}
    if request.query:
        relevant = []
        for entity in candidates:
            score = _relevance_score(entity, request.query)
            if score >= _RELEVANCE_THRESHOLD:
                scores[entity.id] = score
                relevant.append(entity)
        candidates = relevant

    candidates = _sort_matches(candidates, request.sort_by, scores)

    total_matches = len(candidates)
    sliced = candidates[: request.limit]

    duplicate_groups = _find_duplicate_groups(sliced)
    results = [_to_search_result_item(entity, duplicate_groups.get(entity.id)) for entity in sliced]

    return SearchCatalogResponse(
        market_id=request.market_id,
        total_matches=total_matches,
        results=results,
    )
