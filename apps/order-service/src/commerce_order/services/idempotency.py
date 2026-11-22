import hashlib
import json

from commerce_order.api.schemas import Complete, CreateOrder, Reason
from commerce_order.domain.enums import OrderAction

type ActionPayload = Reason | Complete | None


def validate_key(key: str) -> None:
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise ValueError("Idempotency-Key must contain 1 to 128 characters")


def _digest(payload: object) -> str:
    wire = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def creation_hash(request: CreateOrder) -> str:
    payload = request.model_dump(mode="json")
    # Line order is not a change to the purchase. DTOs already normalize UUID/money/text/defaults.
    payload["items"] = sorted(payload["items"], key=lambda item: item["productId"])
    return _digest(payload)


def action_hash(action: OrderAction, payload: ActionPayload) -> str:
    if action in {OrderAction.CANCEL, OrderAction.RECORD_EXCEPTION}:
        if not isinstance(payload, Reason):
            raise ValueError("This action requires a validated reason")
    elif action == OrderAction.COMPLETE:
        if not isinstance(payload, Complete):
            raise ValueError("Completion requires a validated delivery confirmation")
    elif payload is not None:
        raise ValueError("This action does not accept a body")
    return _digest(
        {"action": action.value, "body": payload.model_dump(mode="json") if payload else {}}
    )
