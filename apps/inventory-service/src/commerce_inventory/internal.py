"""Internal endpoints for Catalog availability and Order reconciliation."""

from uuid import UUID

from fastapi import APIRouter, Depends

from commerce_inventory import service
from commerce_inventory.dependencies import InternalSession, require_order
from commerce_inventory.schemas import AvailabilityRequest, AvailabilityResponse, ReservationView

router = APIRouter(prefix="/internal", tags=["Inventory internal"])


@router.post("/availability/batch", response_model=AvailabilityResponse)
async def availability(body: AvailabilityRequest, session: InternalSession) -> AvailabilityResponse:
    return await service.get_availability(session, body)


@router.get(
    "/reservations/by-order/{orderId}",
    response_model=ReservationView,
    dependencies=[Depends(require_order)],
)
async def reservation_by_order(orderId: UUID, session: InternalSession) -> ReservationView:
    return await service.get_reservation_by_order(session, orderId)
