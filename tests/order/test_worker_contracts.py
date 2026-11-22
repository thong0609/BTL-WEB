import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from commerce_backend_common.messaging_topology import EVENT_ROUTES
from commerce_order.messaging.handlers import OPERATIONS
from commerce_order.messaging.schemas import COMMANDS, EVENTS, MessageInvalid, decode_event
from commerce_order.settings import Settings

EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[2] / "docs/order/fixtures/messages.json").read_text(
        encoding="utf-8"
    )
)["examples"]


@pytest.mark.parametrize("example", EXAMPLES, ids=[row["name"] for row in EXAMPLES])
def test_all_existing_message_fixtures_match_typed_payloads(example):
    envelope = example["envelope"]
    if example["kind"] == "event":
        event = decode_event(json.dumps(envelope).encode(), example["routingKey"])
        assert str(event.payload.order_id) == envelope["payload"]["orderId"]
        assert len(event.digest) == 64
    else:
        route, schema = COMMANDS[envelope["type"]]
        assert route == example["routingKey"]
        schema.model_validate(envelope["payload"])


def test_every_contract_event_is_routed_and_has_a_use_case():
    assert len(EVENTS) == 14 and len(COMMANDS) == 8
    assert set(route for route, _ in EVENTS.values()) == set(EVENT_ROUTES)
    assert set(OPERATIONS) | {"PaymentCommandRejected"} == set(EVENTS)


@pytest.mark.parametrize(
    "change",
    [
        "unknown-version",
        "bool-version",
        "unknown-type",
        "wrong-route",
        "integer-money",
        "bool-payment-version",
        "wrong-status",
        "duplicate-items",
    ],
)
def test_invalid_wire_payload_is_rejected_before_database(change):
    name = (
        "PaymentInitialized"
        if change in {"integer-money", "bool-payment-version", "wrong-status"}
        else "StockReserved"
    )
    example = next(row for row in EXAMPLES if row["envelope"]["type"] == name)
    value = copy.deepcopy(example["envelope"])
    route = example["routingKey"]
    if change == "unknown-version":
        value["version"] = 2
    elif change == "bool-version":
        value["version"] = True
    elif change == "unknown-type":
        value["type"] = "UnreviewedResult"
    elif change == "wrong-route":
        route = "payment.refunded"
    elif change == "integer-money":
        value["payload"]["amount"] = 430000
    elif change == "bool-payment-version":
        value["payload"]["paymentVersion"] = True
    elif change == "wrong-status":
        value["payload"]["paymentStatus"] = "SUCCEEDED"
    elif change == "duplicate-items":
        value["payload"]["items"] *= 2
    with pytest.raises(MessageInvalid):
        decode_event(json.dumps(value).encode(), route)


def test_inbox_hash_ignores_json_key_order_but_detects_changed_payload():
    example = next(row for row in EXAMPLES if row["envelope"]["type"] == "StockReserved")
    value = copy.deepcopy(example["envelope"])
    first = decode_event(json.dumps(value).encode(), example["routingKey"])
    assert (
        decode_event(json.dumps(value, sort_keys=True).encode(), example["routingKey"]).digest
        == first.digest
    )
    value["payload"]["items"][0]["quantity"] += 1
    assert decode_event(json.dumps(value).encode(), example["routingKey"]).digest != first.digest


def test_worker_is_explicit_and_default_once_still_means_monitor():
    result = subprocess.run(
        [sys.executable, "-m", "commerce_order.worker"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0 and "--run" in result.stdout and "--mode" in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "commerce_order.worker", "--run", "--mode", "all", "--once"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1 and "BrokerConfigurationError" in result.stdout
    assert "postgresql" not in result.stdout and "amqp://" not in result.stdout


def test_retry_configuration_is_bounded():
    from pydantic import ValidationError

    for options in (
        {"order_event_retry_delays_ms": []},
        {"order_event_retry_delays_ms": [True]},
        {"order_event_max_attempts": 0},
        {"order_outbox_batch_size": 101},
    ):
        with pytest.raises(ValidationError):
            Settings(app_env="test", **options)
