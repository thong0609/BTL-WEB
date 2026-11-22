from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_order.domain.enums import OrderAction
from commerce_order.models import IdempotencyRequest, OrderActionRequest


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def creation(self, customer_id: UUID, key: str) -> IdempotencyRequest | None:
        return await self.session.scalar(
            select(IdempotencyRequest).where(
                IdempotencyRequest.customer_id == customer_id,
                IdempotencyRequest.scope == "CREATE_ORDER",
                IdempotencyRequest.idempotency_key == key,
            )
        )

    async def action(
        self,
        actor_id: UUID,
        order_id: UUID,
        action: OrderAction,
        key: str,
    ) -> OrderActionRequest | None:
        return await self.session.scalar(
            select(OrderActionRequest).where(
                OrderActionRequest.actor_id == actor_id,
                OrderActionRequest.order_id == order_id,
                OrderActionRequest.action == action,
                OrderActionRequest.idempotency_key == key,
            )
        )
