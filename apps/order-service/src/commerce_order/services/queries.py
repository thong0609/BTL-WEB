from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from commerce_backend_common.errors import ServiceError
from commerce_order.api.schemas import (
    History,
    Order,
    OrderPage,
    OrderSummary,
    QuoteItem,
    Recipient,
    WorkflowView,
)
from commerce_order.domain.enums import ActorRole, OrderStatus, WorkflowState
from commerce_order.domain.transitions import Actor, allowed_actions
from commerce_order.models import OrderWorkflow
from commerce_order.repositories.orders import LockedOrder, OrderRepository


def require_role(actor: Actor, *, admin: bool) -> None:
    expected = ActorRole.ADMIN if admin else ActorRole.CUSTOMER
    if actor.role != expected:
        raise ServiceError(403, "FORBIDDEN", "Permission denied")


class OrderQueries:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = OrderRepository(session)

    async def page(
        self,
        actor: Actor,
        *,
        admin: bool = False,
        page: int = 1,
        page_size: int = 20,
        status: OrderStatus | None = None,
        q: str | None = None,
    ) -> OrderPage:
        require_role(actor, admin=admin)
        if (
            type(page) is not int
            or page < 1
            or type(page_size) is not int
            or not 1 <= page_size <= 100
        ):
            raise ServiceError(400, "VALIDATION_ERROR", "Invalid pagination")
        async with self.session.begin():
            # The count and page must describe the same snapshot under concurrent writes.
            await self.session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            rows, total = await self.orders.page(
                customer_id=None if admin else actor.user_id,
                status=status,
                page=page,
                page_size=page_size,
                q=q if admin else None,
            )
            return OrderPage(
                items=[
                    OrderSummary(
                        id=row.id,
                        order_number=row.order_number,
                        status=row.status,
                        payment_status=row.payment_status,
                        total_amount=row.total_amount,
                        currency="VND",
                        created_at=row.created_at,
                    )
                    for row in rows
                ],
                page=page,
                page_size=page_size,
                total=total,
            )

    async def detail(self, actor: Actor, order_id: UUID, *, admin: bool = False) -> Order:
        require_role(actor, admin=admin)
        async with self.session.begin():
            await self.session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            row = await self.orders.get(order_id, None if admin else actor.user_id)
            if row is None:
                raise ServiceError(404, "NOT_FOUND", "Resource not found")
            workflow = await self.session.scalar(
                select(OrderWorkflow).where(OrderWorkflow.order_id == row.id)
            )
            if workflow is None:
                raise ServiceError(503, "ORDER_STATE_UNAVAILABLE", "Order state is unavailable")
            items = await self.orders.items(row.id)
            history = await self.orders.history(row.id)
            facts = LockedOrder(row, workflow).facts()
            return Order(
                id=row.id,
                order_number=row.order_number,
                customer_id=row.customer_id,
                status=row.status,
                payment_id=row.payment_id,
                payment_status=row.payment_status,
                payment_method=row.payment_method,
                items=[
                    QuoteItem(
                        product_id=item.product_id,
                        sku=item.product_sku,
                        name=item.product_name,
                        quantity=item.quantity,
                        unit_price_amount=item.unit_price_amount,
                        line_total_amount=item.line_total_amount,
                        catalog_version=item.catalog_version,
                    )
                    for item in items
                ],
                recipient=Recipient(
                    name=row.recipient_name, phone=row.recipient_phone, address=row.shipping_address
                ),
                note=row.customer_note,
                subtotal_amount=row.subtotal_amount,
                shipping_fee_amount=row.shipping_fee_amount,
                total_amount=row.total_amount,
                currency="VND",
                created_at=row.created_at,
                workflow=WorkflowView(
                    phase=workflow.phase,
                    state=workflow.state,
                    requires_attention=row.requires_attention
                    or workflow.state == WorkflowState.NEEDS_ATTENTION,
                ),
                history=[
                    History(
                        from_status=item.from_status,
                        to_status=item.to_status,
                        reason=item.reason,
                        created_at=item.created_at,
                    )
                    for item in history
                ],
                allowed_actions=list(allowed_actions(facts, actor)),
            )
