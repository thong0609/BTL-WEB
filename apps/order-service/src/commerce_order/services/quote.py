from datetime import UTC, datetime

from commerce_backend_common.errors import ServiceError
from commerce_order.api.schemas import Quote, QuoteInput, QuoteItem
from commerce_order.clients.catalog import CatalogClient
from commerce_order.domain.money import calculate_totals


class QuoteService:
    def __init__(self, catalog: CatalogClient, shipping_fee_amount: int | None) -> None:
        self.catalog = catalog
        self.shipping_fee_amount = shipping_fee_amount

    async def quote(self, request: QuoteInput, request_id: str) -> Quote:
        if self.shipping_fee_amount is None:
            raise ServiceError(503, "DEPENDENCY_UNAVAILABLE", "Shipping fee is not configured")
        products = await self.catalog.products(
            [item.product_id for item in request.items], request_id
        )
        try:
            totals = calculate_totals(
                ((products[item.product_id].price_amount, item.quantity) for item in request.items),
                self.shipping_fee_amount,
            )
            items = [
                QuoteItem(
                    product_id=item.product_id,
                    sku=products[item.product_id].sku,
                    name=products[item.product_id].name,
                    quantity=item.quantity,
                    unit_price_amount=products[item.product_id].price_amount,
                    line_total_amount=products[item.product_id].price_amount * item.quantity,
                    catalog_version=products[item.product_id].version,
                )
                for item in request.items
            ]
            return Quote(
                items=items,
                subtotal_amount=totals.subtotal_amount,
                shipping_fee_amount=totals.shipping_fee_amount,
                total_amount=totals.total_amount,
                currency="VND",
                quoted_at=datetime.now(UTC),
            )
        except ValueError as exc:
            raise ServiceError(
                400, "VALIDATION_ERROR", "Order amounts exceed supported limits"
            ) from exc
