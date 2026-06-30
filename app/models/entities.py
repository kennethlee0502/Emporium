# Discriminated-union entity models (CLAUDE.md S2.3, S3.1, S3.2).
#
# catalog.json holds five record shapes under one `type` discriminator:
# product, gift_card, collection, page, bundle. Price is modeled as an
# explicit (value, state) pair so the four documented price states -
# normal, null, missing, non_positive - stay distinguishable downstream
# instead of collapsing into a single nullable float (CLAUDE.md S3.2).
#
# extra="forbid" is used deliberately: an unexpected field on a future
# catalog record should surface as a quarantined record at ingestion
# (Task 4), not be silently dropped here.

from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class PriceState(str, Enum):
    NORMAL = "normal"
    NULL = "null"
    MISSING = "missing"
    NON_POSITIVE = "non_positive"


def _resolve_price(data: object) -> object:
    """Classify the raw `price` value before field validation runs."""
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if "price" not in data:
        data["price"] = None
        data["price_state"] = PriceState.MISSING
        return data
    raw = data["price"]
    if raw is None:
        data["price_state"] = PriceState.NULL
        return data
    value = float(raw)  # unparseable strings raise -> Pydantic wraps as ValidationError for the loader to quarantine
    data["price"] = value
    data["price_state"] = PriceState.NON_POSITIVE if value <= 0 else PriceState.NORMAL
    return data


class CatalogEntityBase(BaseModel):
    """Fields shared by every entity shape in catalog.json."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    market_id: str
    language: str
    description: str
    category: Optional[str] = None


class PricedMixin(BaseModel):
    """Shared price-state handling for entity types that carry a price."""

    model_config = ConfigDict(extra="forbid")

    price: Optional[float] = None
    price_state: PriceState
    currency: str

    @model_validator(mode="before")
    @classmethod
    def _set_price_state(cls, data: object) -> object:
        return _resolve_price(data)


class Product(CatalogEntityBase, PricedMixin):
    type: Literal["product"]
    product_group_id: str
    tags: Optional[List[str]] = None
    stock_qty: int
    available: bool
    rating: float
    review_count: int
    top_review: Optional[str] = None


class GiftCard(CatalogEntityBase, PricedMixin):
    type: Literal["gift_card"]
    denominations: List[float]
    available: bool


class Collection(CatalogEntityBase):
    type: Literal["collection"]
    member_ids: List[str]


class Page(CatalogEntityBase):
    type: Literal["page"]


class Bundle(CatalogEntityBase, PricedMixin):
    type: Literal["bundle"]
    member_ids: List[str]
    stock_qty: int
    available: bool
    tags: Optional[List[str]] = None


CatalogEntity = Annotated[
    Union[Product, GiftCard, Collection, Page, Bundle],
    Field(discriminator="type"),
]

catalog_entity_adapter = TypeAdapter(CatalogEntity)
