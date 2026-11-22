import copy
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from commerce_order.api.schemas import (
    Complete,
    CreateOrder,
    Order,
    OrderPage,
    Quote,
    QuoteInput,
    Reason,
    Recipient,
)
from commerce_order.domain.enums import PaymentMethod
from commerce_order.domain.money import PG_BIGINT_MAX
from commerce_order.main import create_app
from commerce_order.settings import Settings


def test_existing_http_fixtures_roundtrip_camel_case_string_money(create_payload, quote_payload):
    order = CreateOrder.model_validate(create_payload)
    assert order.items[0].expected_unit_price_amount == 200000
    assert order.model_dump(mode="json") == create_payload
    quote = Quote.model_validate(quote_payload)
    assert quote.model_dump(mode="json") == quote_payload
    assert quote.total_amount == 430000


@pytest.mark.parametrize("value", [True, False, 2.0, "2", 0, -1, 1000, None])
def test_quantities_are_strict_integers(create_payload, value):
    create_payload["items"][0]["quantity"] = value
    with pytest.raises(ValidationError):
        CreateOrder.model_validate(create_payload)


@pytest.mark.parametrize("field", ["customerId", "status", "totalAmount", "simulationScenario"])
def test_checkout_cannot_supply_authority_fields(create_payload, field):
    create_payload[field] = "forged"
    with pytest.raises(ValidationError):
        CreateOrder.model_validate(create_payload)


def test_http_input_does_not_silently_accept_snake_case_or_bad_ids(create_payload):
    create_payload["payment_method"] = create_payload.pop("paymentMethod")
    with pytest.raises(ValidationError):
        CreateOrder.model_validate(create_payload)
    with pytest.raises(ValidationError):
        QuoteInput.model_validate({"items": [{"productId": "not-a-uuid", "quantity": 1}]})


@pytest.mark.parametrize("field", ["expectedUnitPriceAmount", "expectedCatalogVersion"])
def test_confirmed_price_and_version_cannot_be_coerced(create_payload, field):
    create_payload["items"][0][field] = True if field.endswith("Version") else 200000
    with pytest.raises(ValidationError):
        CreateOrder.model_validate(create_payload)


def test_duplicate_products_are_detected_after_uuid_normalization(create_payload):
    item = create_payload["items"][0]
    item["productId"] = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    create_payload["items"].append({**item, "productId": item["productId"].lower()})
    with pytest.raises(ValidationError, match="Duplicate products"):
        CreateOrder.model_validate(create_payload)


def test_quote_and_create_both_bound_line_counts_and_duplicates(create_payload):
    for count in (0, 51):
        items = [{"productId": str(UUID(int=i + 1)), "quantity": 1} for i in range(count)]
        with pytest.raises(ValidationError):
            QuoteInput.model_validate({"items": items})
        create_payload["items"] = [
            {**item, "expectedUnitPriceAmount": "1", "expectedCatalogVersion": 0} for item in items
        ]
        with pytest.raises(ValidationError):
            CreateOrder.model_validate(create_payload)
    items = [{"productId": str(UUID(int=i + 1)), "quantity": 999} for i in range(50)]
    assert len(QuoteInput.model_validate({"items": items}).items) == 50
    with pytest.raises(ValidationError):
        QuoteInput.model_validate({"items": [items[0], items[0]]})


@pytest.mark.parametrize(
    "amount", [True, 30000, 30000.0, "-1", "1.5", "１２", str(PG_BIGINT_MAX + 1)]
)
def test_shipping_money_is_a_bounded_ascii_string(create_payload, amount):
    create_payload["expectedShippingFeeAmount"] = amount
    with pytest.raises(ValidationError):
        CreateOrder.model_validate(create_payload)


def test_recipient_and_reason_trim_before_length_checks(create_payload):
    recipient = Recipient.model_validate(
        {"name": "  A  ", "phone": " +84900000001 ", "address": "  12 đường giả lập  "}
    )
    assert recipient.name == "A" and recipient.address == "12 đường giả lập"
    assert Reason.model_validate({"reason": "  Khách yêu cầu hủy  "}).reason == "Khách yêu cầu hủy"
    for key, value in (("name", "   "), ("address", "  ngắn  "), ("phone", "123")):
        with pytest.raises(ValidationError):
            Recipient.model_validate({**create_payload["recipient"], key: value})
    for reason in ("   ", "x" * 1001):
        with pytest.raises(ValidationError):
            Reason.model_validate({"reason": reason})


def test_optional_request_fields_may_be_omitted_but_not_null(create_payload):
    create_payload.pop("note")
    assert CreateOrder.model_validate(create_payload).note == ""
    create_payload["note"] = None
    with pytest.raises(ValidationError):
        CreateOrder.model_validate(create_payload)
    with pytest.raises(ValidationError):
        Complete.model_validate({"delivered": True, "codCollected": None})


@pytest.mark.parametrize(
    "field,value",
    [
        ("subtotalAmount", "399999"),
        ("totalAmount", "430001"),
        ("currency", "USD"),
    ],
)
def test_response_snapshots_cannot_contain_inconsistent_totals(quote_payload, field, value):
    quote_payload[field] = value
    with pytest.raises(ValidationError):
        Quote.model_validate(quote_payload)


def test_response_checks_line_arithmetic_and_duplicate_skus(quote_payload):
    quote_payload["items"][0]["lineTotalAmount"] = "1"
    with pytest.raises(ValidationError):
        Quote.model_validate(quote_payload)
    quote_payload["items"][0]["lineTotalAmount"] = "400000"
    quote_payload["items"].append({**quote_payload["items"][0], "productId": str(UUID(int=99))})
    with pytest.raises(ValidationError, match="Duplicate SKUs"):
        Quote.model_validate(quote_payload)


def test_money_from_internal_integers_still_serializes_as_strings(quote_payload):
    for key in ("subtotalAmount", "shippingFeeAmount", "totalAmount"):
        quote_payload[key] = int(quote_payload[key])
    for key in ("unitPriceAmount", "lineTotalAmount"):
        quote_payload["items"][0][key] = int(quote_payload["items"][0][key])
    payload = Quote.model_validate(quote_payload).model_dump(mode="json")
    assert payload["totalAmount"] == "430000" and payload["items"][0]["unitPriceAmount"] == "200000"


def test_timestamps_must_have_timezone_and_normalize_to_utc(quote_payload):
    quote_payload["quotedAt"] = "2026-11-07T09:00:00+07:00"
    assert (
        Quote.model_validate(quote_payload).model_dump(mode="json")["quotedAt"]
        == "2026-11-07T02:00:00Z"
    )
    quote_payload["quotedAt"] = "2026-11-07T09:00:00"
    with pytest.raises(ValidationError):
        Quote.model_validate(quote_payload)


@pytest.mark.parametrize("delivered", [False, 1, 0, "true", None])
def test_complete_requires_the_literal_boolean_true(delivered):
    with pytest.raises(ValidationError):
        Complete.model_validate({"delivered": delivered})


def test_cod_requires_collection_confirmation_but_simulated_does_not_charge_again():
    request = Complete.model_validate({"delivered": True})
    request.validate_for_payment_method(PaymentMethod.SIMULATED)
    with pytest.raises(ValueError, match="COD"):
        request.validate_for_payment_method(PaymentMethod.COD)
    Complete.model_validate({"delivered": True, "codCollected": True}).validate_for_payment_method(
        PaymentMethod.COD
    )
    for value in (1, "true"):
        with pytest.raises(ValidationError):
            Complete.model_validate({"delivered": True, "codCollected": value})


def test_public_order_view_contains_no_internal_workflow_data(create_payload, quote_payload):
    payload = {k: v for k, v in quote_payload.items() if k != "quotedAt"}
    payload.update(
        id=str(UUID(int=101)),
        orderNumber="DEMO-001",
        customerId=str(UUID(int=1)),
        status="PROCESSING",
        paymentId=None,
        paymentStatus=None,
        paymentMethod="COD",
        recipient=create_payload["recipient"],
        note=None,
        createdAt=quote_payload["quotedAt"],
        workflow={"phase": "CHECKOUT", "state": "WAITING", "requiresAttention": False},
        history=[
            {
                "fromStatus": None,
                "toStatus": "PROCESSING",
                "reason": None,
                "createdAt": quote_payload["quotedAt"],
            }
        ],
        allowedActions=[],
    )
    assert Order.model_validate(payload).model_dump(mode="json") == payload
    changed = copy.deepcopy(payload)
    changed["workflow"]["operationId"] = str(UUID(int=501))
    with pytest.raises(ValidationError):
        Order.model_validate(changed)


@pytest.mark.parametrize(
    "field,value", [("page", 0), ("pageSize", 101), ("total", -1), ("page", True)]
)
def test_public_pagination_bounds(field, value):
    payload = {"items": [], "page": 1, "pageSize": 20, "total": 0, field: value}
    with pytest.raises(ValidationError):
        OrderPage.model_validate(payload)


def test_schema_validation_uses_existing_http_400_envelope(create_payload):
    app = create_app(Settings(app_env="test"))

    @app.post("/_test/order-schema")
    def schema_probe(body: CreateOrder):
        return {"total": body.expected_shipping_fee_amount}

    with TestClient(app) as client:
        assert client.post("/_test/order-schema", json=create_payload).status_code == 200
        create_payload["customerId"] = str(UUID(int=55))
        response = client.post("/_test/order-schema", json=create_payload)
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["requestId"] == response.headers["X-Request-Id"]
