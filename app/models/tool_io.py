# Per-tool request/response schemas - the function-calling contract
# (CLAUDE.md S2.3, S3.5, S3.6, S5.2).
#
# This file IS what the calling agent sees: FastAPI derives the OpenAPI/
# function-calling tool definitions directly from these models, so every
# field carries an explicit Field(description=...) rather than relying on
# a human reading the source.
#
# market_id is required (no default) on every commerce-facing request
# model - never Optional[str] = None - per CLAUDE.md S5.2: this is the one
# control that prevents a request scoped to one market from leaking a
# different market's price/currency. Omitting it must raise a
# ValidationError, not silently default to some market.
#
# Business logic (search ranking, market-variant resolution, cart pricing)
# is implemented in app/services/* in later tasks - this module only
# defines the shapes.

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# search_catalog
# ---------------------------------------------------------------------------


class SearchCatalogRequest(BaseModel):
    """Search the catalog for purchasable products, bundles, and gift cards within one market."""

    model_config = ConfigDict(extra="forbid")

    market_id: str = Field(
        description=(
            "Required market scope for this search, e.g. 'us', 'fr', 'de', 'uk'. "
            "Results are restricted to this market only - prices and currencies "
            "are never compared or mixed across markets."
        )
    )
    query: Optional[str] = Field(
        default=None,
        description="Free-text search query matched against product name, description, and tags.",
    )
    category: Optional[str] = Field(
        default=None,
        description="Restrict results to this exact category facet, e.g. 'apparel' or 'footwear'.",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Restrict results to items having at least one of these tags (OR match).",
    )
    min_price: Optional[float] = Field(
        default=None,
        ge=0,
        description="Minimum price filter, inclusive, in the requested market's currency.",
    )
    max_price: Optional[float] = Field(
        default=None,
        ge=0,
        description="Maximum price filter, inclusive, in the requested market's currency.",
    )
    in_stock_only: bool = Field(
        default=False,
        description="If true, only return items that are currently purchasable (see is_purchasable policy).",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of results to return.",
    )
    sort_by: Literal["relevance", "price_asc", "price_desc", "rating_desc"] = Field(
        default="relevance",
        description="Result ordering: 'relevance' (default), 'price_asc', 'price_desc', or 'rating_desc'.",
    )


class SearchResultItem(BaseModel):
    """A single catalog entity matched by search_catalog."""

    id: str = Field(description="The catalog entity id.")
    type: Literal["product", "gift_card", "bundle"] = Field(
        description="The kind of entity this result represents."
    )
    name: str = Field(description="Display name of the item.")
    category: Optional[str] = Field(default=None, description="Category facet, if any.")
    price: Optional[float] = Field(
        default=None,
        description="Price in the requested market's currency, or null if not fixed-priced (see price_state).",
    )
    currency: Optional[str] = Field(default=None, description="ISO currency code for `price`, e.g. 'USD'.")
    price_state: str = Field(
        description=(
            "One of 'normal', 'null', 'missing', 'non_positive'. Explains why `price` may be "
            "null or how it should be interpreted - see CLAUDE.md S3.2."
        )
    )
    is_purchasable: bool = Field(
        description="True if this item can be sold right now, per the pricing policy (CLAUDE.md S3.3)."
    )
    rating: Optional[float] = Field(default=None, description="Average customer rating, if applicable.")
    review_count: Optional[int] = Field(default=None, description="Number of customer reviews, if applicable.")
    tags: Optional[List[str]] = Field(default=None, description="Descriptive tags attached to this item.")
    possible_duplicate_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "Ids of other catalog entities with a near-identical name, surfaced as an advisory "
            "only - these are never auto-merged (CLAUDE.md S3.4)."
        ),
    )


class SearchCatalogResponse(BaseModel):
    """Results of a search_catalog call."""

    market_id: str = Field(description="Echoes the market_id this search was scoped to.")
    total_matches: int = Field(description="Total number of matching items before `limit` was applied.")
    results: List[SearchResultItem] = Field(description="The matched items, ordered by `sort_by`.")


# ---------------------------------------------------------------------------
# get_product_details
# ---------------------------------------------------------------------------


class GetProductDetailsRequest(BaseModel):
    """Fetch full details for a single product, resolved to a specific market."""

    model_config = ConfigDict(extra="forbid")

    market_id: str = Field(
        description="Required market to resolve this product in, e.g. 'us', 'fr', 'de', 'uk'."
    )
    product_id: str = Field(
        description=(
            "The product id or product_group_id to retrieve. If the exact id is not itself "
            "available in the requested market, its localized siblings (linked via "
            "product_group_id) are checked instead."
        )
    )


class ProductDetail(BaseModel):
    """Full detail record for a single product, already resolved to one market."""

    id: str = Field(description="The catalog entity id of this market-specific product record.")
    product_group_id: str = Field(
        description="Groups this product with its localized siblings across markets."
    )
    market_id: str = Field(description="The market this specific record belongs to.")
    name: str = Field(description="Display name of the product.")
    category: Optional[str] = Field(default=None, description="Category facet, if any.")
    description: str = Field(description="Full product description text.")
    price: Optional[float] = Field(
        default=None,
        description="Price in this market's currency, or null if not fixed-priced (see price_state).",
    )
    currency: Optional[str] = Field(default=None, description="ISO currency code for `price`, e.g. 'USD'.")
    price_state: str = Field(
        description="One of 'normal', 'null', 'missing', 'non_positive' - see CLAUDE.md S3.2."
    )
    is_purchasable: bool = Field(
        description="True if this item can be sold right now, per the pricing policy (CLAUDE.md S3.3)."
    )
    stock_qty: int = Field(description="Raw inventory count. Not the same as purchasability - see CLAUDE.md S3.3.")
    available: bool = Field(description="Independent commercial availability flag, not derived from stock_qty.")
    rating: float = Field(description="Average customer rating.")
    review_count: int = Field(description="Number of customer reviews.")
    tags: Optional[List[str]] = Field(default=None, description="Descriptive tags attached to this product.")


class LocalizedVariantSummary(BaseModel):
    """Summary of one other market's localized version of a resolved product (CLAUDE.md S1.9)."""

    id: str = Field(description="The catalog entity id of this market-specific variant.")
    market_id: str = Field(description="The market this variant belongs to.")
    name: str = Field(description="Display name of the product in this market.")
    price: Optional[float] = Field(
        default=None,
        description="Price in this variant's own currency, or null if not fixed-priced. Never FX-converted from another market.",
    )
    currency: Optional[str] = Field(default=None, description="ISO currency code for `price`, e.g. 'EUR'.")
    price_state: str = Field(
        description="One of 'normal', 'null', 'missing', 'non_positive' - see CLAUDE.md S3.2."
    )
    is_purchasable: bool = Field(
        description="True if this variant can be sold right now in its own market, per the pricing policy."
    )


class GetProductDetailsResponse(BaseModel):
    """Result of a get_product_details call."""

    requested_product_id: str = Field(description="Echoes product_id from the request, for traceability.")
    market_id: str = Field(description="Echoes market_id from the request.")
    resolved: bool = Field(
        description="True if a product was found and is available in the requested market."
    )
    product: Optional[ProductDetail] = Field(
        default=None, description="The resolved product detail. Present only when `resolved` is true."
    )
    localized_variants: List[LocalizedVariantSummary] = Field(
        default_factory=list,
        description=(
            "Other markets' localized versions of this same product (same product_group_id), "
            "excluding the resolved market itself. Each market's price/currency is independently "
            "authored, never FX-converted - see CLAUDE.md S1.9. Empty when `resolved` is false or "
            "no other market carries this product."
        ),
    )
    unresolved_reason: Optional[str] = Field(
        default=None,
        description=(
            "Human-readable reason the product could not be resolved in this market "
            "(e.g. 'no localized variant exists for this market'). Present only when "
            "`resolved` is false."
        ),
    )


# ---------------------------------------------------------------------------
# calculate_cart
# ---------------------------------------------------------------------------


class CartLineItem(BaseModel):
    """A single requested line item for cart calculation. Carries no persisted state."""

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(description="The catalog entity id of the product, bundle, or gift card to price.")
    quantity: int = Field(ge=1, description="Number of units of this item, at least 1.")
    gift_card_denomination: Optional[float] = Field(
        default=None,
        description=(
            "Required when product_id refers to a gift card; the chosen denomination amount. "
            "Ignored for non-gift-card items."
        ),
    )


class CalculateCartRequest(BaseModel):
    """Compute a stateless price breakdown for a set of line items. No cart is persisted anywhere."""

    model_config = ConfigDict(extra="forbid")

    market_id: str = Field(
        description=(
            "Required single market scope for this calculation, e.g. 'us', 'fr', 'de', 'uk'. "
            "Every line item is priced in this market; items only available in a different "
            "market are rejected, never silently re-priced."
        )
    )
    line_items: List[CartLineItem] = Field(
        min_length=1, description="The items to price. At least one line item is required."
    )


class CartLineItemResult(BaseModel):
    """A successfully priced line item."""

    product_id: str = Field(description="The catalog entity id that was priced.")
    name: str = Field(description="Display name of the priced item.")
    quantity: int = Field(description="Number of units priced.")
    unit_price: float = Field(description="Price per unit in the cart's currency.")
    line_total: float = Field(description="unit_price multiplied by quantity.")
    currency: str = Field(description="ISO currency code for this line, matching the cart's market.")


class RejectedLineItem(BaseModel):
    """A requested line item that could not be priced, with an explicit reason - never silently dropped."""

    product_id: str = Field(description="The catalog entity id that was requested.")
    quantity: int = Field(description="Number of units that were requested.")
    reason: str = Field(
        description=(
            "Why this line item was rejected, e.g. 'not purchasable', 'id not found in this "
            "market', 'gift card denomination required', or 'denomination not offered for this gift card'."
        )
    )


class CalculateCartResponse(BaseModel):
    """Result of a calculate_cart call. Computed fresh from the request every time - nothing is persisted."""

    market_id: str = Field(description="Echoes the market_id this calculation was scoped to.")
    currency: Optional[str] = Field(
        default=None,
        description="ISO currency code for this market's prices. Null only if every line item was rejected.",
    )
    line_items: List[CartLineItemResult] = Field(description="Successfully priced line items.")
    rejected_items: List[RejectedLineItem] = Field(
        description="Requested line items that could not be priced, each with an explicit reason."
    )
    subtotal: float = Field(description="Sum of line_total across all successfully priced line items.")
