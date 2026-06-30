# Tool I/O contract regression tests (CLAUDE.md S3.5, S3.6, S5.2).
#
# Two things are verified here:
#   1. market_id is a genuinely required field (no default) on every
#      commerce-facing request model - the control that prevents a request
#      scoped to one market from leaking another market's price/currency.
#   2. Every field on every model in this module has a non-empty
#      Field(description=...), since these models ARE the OpenAPI/
#      function-calling contract the upstream agent reads.

import inspect

import pytest
from pydantic import BaseModel, ValidationError

import app.models.tool_io as tool_io
from app.models.tool_io import (
    CalculateCartRequest,
    CartLineItem,
    GetProductDetailsRequest,
    SearchCatalogRequest,
)


def _all_tool_io_models():
    return [
        obj
        for _name, obj in vars(tool_io).items()
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel
    ]


@pytest.mark.parametrize(
    "model_cls, payload",
    [
        (SearchCatalogRequest, {}),
        (GetProductDetailsRequest, {"product_id": "prod_000"}),
        (
            CalculateCartRequest,
            {"line_items": [{"product_id": "prod_000", "quantity": 1}]},
        ),
    ],
)
def test_market_id_is_required_on_every_commerce_request_model(model_cls, payload):
    with pytest.raises(ValidationError) as exc_info:
        model_cls(**payload)
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("market_id",) and err["type"] == "missing" for err in errors)


@pytest.mark.parametrize(
    "model_cls, payload",
    [
        (SearchCatalogRequest, {"market_id": "us"}),
        (GetProductDetailsRequest, {"market_id": "us", "product_id": "prod_000"}),
        (
            CalculateCartRequest,
            {"market_id": "us", "line_items": [{"product_id": "prod_000", "quantity": 1}]},
        ),
    ],
)
def test_request_models_succeed_once_market_id_is_present(model_cls, payload):
    instance = model_cls(**payload)
    assert instance.market_id == "us"


def test_every_field_in_every_tool_io_model_has_a_description():
    missing = []
    for model_cls in _all_tool_io_models():
        schema = model_cls.model_json_schema()
        property_groups = [schema.get("properties", {})]
        for nested_schema in schema.get("$defs", {}).values():
            property_groups.append(nested_schema.get("properties", {}))
        for properties in property_groups:
            for field_name, field_schema in properties.items():
                if not field_schema.get("description"):
                    missing.append(f"{model_cls.__name__}.{field_name}")
    assert missing == [], f"Fields missing Field(description=...): {missing}"


def test_every_tool_io_model_has_a_model_level_description():
    missing = [
        model_cls.__name__
        for model_cls in _all_tool_io_models()
        if not (model_cls.__doc__ and model_cls.__doc__.strip())
    ]
    assert missing == [], f"Models missing a docstring (used as the schema description): {missing}"


def test_search_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        SearchCatalogRequest(market_id="us", not_a_real_field="oops")


def test_search_request_limit_is_bounded():
    with pytest.raises(ValidationError):
        SearchCatalogRequest(market_id="us", limit=0)
    with pytest.raises(ValidationError):
        SearchCatalogRequest(market_id="us", limit=101)
    assert SearchCatalogRequest(market_id="us", limit=100).limit == 100


def test_cart_line_item_quantity_must_be_at_least_one():
    with pytest.raises(ValidationError):
        CartLineItem(product_id="prod_000", quantity=0)


def test_cart_request_requires_at_least_one_line_item():
    with pytest.raises(ValidationError):
        CalculateCartRequest(market_id="us", line_items=[])
