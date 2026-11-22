from pathlib import Path

import pytest
import yaml

from commerce_order.api import schemas
from commerce_order.clients.catalog import CatalogBatch, CatalogProduct
from commerce_order.domain.enums import OrderAction, OrderStatus, PaymentStatus

SPEC = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "docs/contracts/openapi.yaml").read_text(
        encoding="utf-8"
    )
)["components"]["schemas"]


@pytest.mark.parametrize(
    "name",
    [
        "CartItem",
        "QuoteInput",
        "ConfirmedItem",
        "Recipient",
        "CreateOrder",
        "QuoteItem",
        "Quote",
        "OrderAccepted",
        "ActionResult",
        "History",
        "Order",
        "OrderSummary",
        "OrderPage",
        "Reason",
        "Complete",
    ],
)
def test_published_fields_and_required_fields_match_openapi(name):
    model = getattr(schemas, name)
    for mode in ("validation", "serialization"):
        generated = model.model_json_schema(mode=mode)
        expected = SPEC[name]
        assert set(generated["properties"]) == set(expected["properties"])
        assert set(generated.get("required", [])) == set(expected.get("required", []))
        assert generated["additionalProperties"] is False


def test_status_and_action_names_match_the_public_contract():
    assert [status.value for status in OrderStatus] == SPEC["OrderStatus"]["enum"]
    assert [status.value for status in PaymentStatus] == SPEC["PaymentStatus"]["enum"]
    assert [action.value for action in OrderAction] == SPEC["Order"]["properties"][
        "allowedActions"
    ]["items"]["enum"]


def test_generated_money_and_delivery_schema_preserve_wire_types():
    for model, fields in (
        (schemas.CreateOrder, ["expectedShippingFeeAmount"]),
        (schemas.ConfirmedItem, ["expectedUnitPriceAmount"]),
        (schemas.Quote, ["subtotalAmount", "shippingFeeAmount", "totalAmount"]),
    ):
        for mode in ("validation", "serialization"):
            properties = model.model_json_schema(mode=mode)["properties"]
            for field in fields:
                assert properties[field]["type"] == "string"
                assert properties[field]["pattern"] == "^[0-9]+$"
    delivered = schemas.Complete.model_json_schema()["properties"]["delivered"]
    assert delivered["type"] == "boolean" and delivered["const"] is True


def test_step_one_action_and_checkout_examples_are_consumable(http_examples):
    models = {
        "quote": schemas.QuoteInput,
        "create_cod": schemas.CreateOrder,
        "create_simulated": schemas.CreateOrder,
        "cancel_paid": schemas.Reason,
        "record_exception": schemas.Reason,
        "complete_cod": schemas.Complete,
    }
    for name, model in models.items():
        model.model_validate(http_examples[name]["requestBody"])
    for name in ("create_cod", "create_simulated"):
        schemas.OrderAccepted.model_validate(http_examples[name]["responseBody"])


def test_order_catalog_adapter_matches_proposed_internal_contract():
    draft = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2] / "docs/contracts/catalog-internal.openapi.yaml"
        ).read_text(encoding="utf-8")
    )
    assert draft["info"]["version"].endswith("draft")
    operation = draft["paths"]["/internal/products/batch"]["post"]
    assert operation["security"] == [{"serviceBearer": []}]
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert CatalogBatch.model_json_schema()["required"] == response["required"]
    generated = CatalogProduct.model_json_schema()
    expected = draft["components"]["schemas"]["BatchProduct"]
    assert set(generated["required"]) == set(expected["required"])
    assert set(generated["properties"]) == set(expected["properties"])
    for field in ("status", "currency", "priceAmount", "version"):
        actual = generated["properties"][field]
        if "const" in actual:
            actual["enum"] = [actual["const"]]
        for keyword in ("type", "pattern", "minimum", "maximum", "enum"):
            if keyword in expected["properties"][field]:
                assert actual[keyword] == expected["properties"][field][keyword]
