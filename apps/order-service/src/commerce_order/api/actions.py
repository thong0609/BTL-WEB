"""Shared HTTP adapter; only public errors and ActionResult leave this boundary."""

from uuid import UUID

from sqlalchemy.exc import DBAPIError

from commerce_backend_common.errors import ServiceError
from commerce_order.api.schemas import ActionResult
from commerce_order.domain.enums import OrderAction
from commerce_order.domain.transitions import Actor, OrderRuleViolation
from commerce_order.services.actions import OrderActions
from commerce_order.services.idempotency import ActionPayload
from commerce_order.services.persistence import OrderPersistence


async def execute(
    actor: Actor,
    store: OrderPersistence,
    order_id: UUID,
    action: OrderAction,
    key: str,
    payload: ActionPayload = None,
) -> ActionResult:
    try:
        response = await OrderActions(store).accept(actor, order_id, action, key, payload)
    except OrderRuleViolation as exc:
        status = {"NOT_FOUND": 404, "FORBIDDEN": 403}.get(exc.code, 409)
        raise ServiceError(status, exc.code, "Order action is not allowed") from None
    except ValueError:
        raise ServiceError(400, "VALIDATION_ERROR", "Invalid action confirmation") from None
    except DBAPIError:
        raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Order storage is unavailable") from None
    return ActionResult.model_validate(response.body)
