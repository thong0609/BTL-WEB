"""Integer VND calculations bounded by the PostgreSQL bigint storage type."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

PG_BIGINT_MAX = (1 << 63) - 1
MAX_ORDER_ITEMS = 50
MAX_QUANTITY = 999


def validate_amount(value: int) -> int:
    if type(value) is not int or not 0 <= value <= PG_BIGINT_MAX:
        raise ValueError("Money must be a nonnegative PostgreSQL bigint")
    return value


def parse_money_string(value: object) -> int:
    """Parse the wire format, without accepting JSON numbers, signs or Unicode digits."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError("Money must be an ASCII integer string")
    digits = value.lstrip("0") or "0"
    if len(digits) > 19:
        raise ValueError("Money exceeds the PostgreSQL bigint limit")
    return validate_amount(int(digits))


def line_total(unit_price_amount: int, quantity: int) -> int:
    validate_amount(unit_price_amount)
    if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
        raise ValueError("Quantity must be an integer between 1 and 999")
    return validate_amount(unit_price_amount * quantity)


@dataclass(frozen=True)
class OrderTotals:
    subtotal_amount: int
    shipping_fee_amount: int
    total_amount: int


def calculate_totals(lines: Iterable[tuple[int, int]], shipping_fee_amount: int) -> OrderTotals:
    """Each line is (unit_price_amount, quantity); every intermediate sum is bounded."""
    validate_amount(shipping_fee_amount)
    subtotal = 0
    count = 0
    for count, (price, quantity) in enumerate(lines, start=1):
        if count > MAX_ORDER_ITEMS:
            raise ValueError("An order cannot contain more than 50 lines")
        subtotal = validate_amount(subtotal + line_total(price, quantity))
    if count == 0:
        raise ValueError("An order must contain at least one line")
    return OrderTotals(
        subtotal_amount=subtotal,
        shipping_fee_amount=shipping_fee_amount,
        total_amount=validate_amount(subtotal + shipping_fee_amount),
    )
