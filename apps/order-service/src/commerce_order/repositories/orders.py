from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_order.domain.enums import OrderStatus
from commerce_order.domain.transitions import OrderFacts
from commerce_order.models import OrderItem, OrderRecord, OrderStatusHistory, OrderWorkflow


@dataclass(frozen=True)
class LockedOrder:
    order: OrderRecord
    workflow: OrderWorkflow

    def facts(self) -> OrderFacts:
        return OrderFacts(
            customer_id=self.order.customer_id,
            status=self.order.status,
            payment_method=self.order.payment_method,
            payment_status=self.order.payment_status,
            stock_step=self.workflow.stock_step,
            workflow_phase=self.workflow.phase,
            workflow_state=self.workflow.state,
        )


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, order_id: UUID, customer_id: UUID | None = None) -> OrderRecord | None:
        query = select(OrderRecord).where(OrderRecord.id == order_id)
        if customer_id is not None:
            query = query.where(OrderRecord.customer_id == customer_id)
        return await self.session.scalar(query)

    async def lock(self, order_id: UUID) -> LockedOrder | None:
        # Every writer must lock the header first, then workflow. Never reverse this order.
        order = await self.session.scalar(
            select(OrderRecord).where(OrderRecord.id == order_id).with_for_update()
        )
        if order is None:
            return None
        workflow = await self.session.scalar(
            select(OrderWorkflow).where(OrderWorkflow.order_id == order_id).with_for_update()
        )
        if workflow is None:
            raise ValueError("ORDER_WORKFLOW_MISSING")
        return LockedOrder(order, workflow)

    async def items(self, order_id: UUID) -> list[OrderItem]:
        return list(
            await self.session.scalars(
                select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
            )
        )

    async def history(self, order_id: UUID) -> list[OrderStatusHistory]:
        return list(
            await self.session.scalars(
                select(OrderStatusHistory)
                .where(OrderStatusHistory.order_id == order_id)
                .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
            )
        )

    async def page(
        self,
        *,
        customer_id: UUID | None,
        status: OrderStatus | None,
        page: int,
        page_size: int,
        q: str | None = None,
    ) -> tuple[list[OrderRecord], int]:
        filters = []
        if customer_id is not None:
            filters.append(OrderRecord.customer_id == customer_id)
        if status is not None:
            filters.append(OrderRecord.status == status)
        if q and q.strip():
            filters.append(OrderRecord.order_number.icontains(q.strip(), autoescape=True))
        total = await self.session.scalar(
            select(func.count()).select_from(OrderRecord).where(*filters)
        )
        records = await self.session.scalars(
            select(OrderRecord)
            .where(*filters)
            .order_by(OrderRecord.created_at.desc(), OrderRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(records), int(total or 0)
