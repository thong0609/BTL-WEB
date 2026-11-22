import pytest

from commerce_order.domain.money import (
    PG_BIGINT_MAX,
    calculate_totals,
    line_total,
    parse_money_string,
)


def test_vnd_totals_use_integers_and_snapshot_shipping():
    totals = calculate_totals([(200000, 2)], 30000)
    assert (totals.subtotal_amount, totals.shipping_fee_amount, totals.total_amount) == (
        400000,
        30000,
        430000,
    )
    assert calculate_totals([(200000, 2), (500000, 1)], 0).total_amount == 900000
    assert calculate_totals([(0, 1)], 0).total_amount == 0


@pytest.mark.parametrize("quantity", [True, False, 1.0, "2", 0, -1, 1000])
def test_quantity_cannot_be_coerced_or_outside_limits(quantity):
    with pytest.raises(ValueError):
        line_total(200000, quantity)


@pytest.mark.parametrize("value", [True, 2, 1.0, None, "", "-1", "+2", "2.0", " 2", "2\n", "１２"])
def test_wire_money_is_only_an_ascii_integer_string(value):
    with pytest.raises(ValueError):
        parse_money_string(value)


def test_money_boundaries_and_leading_zero_normalization():
    assert parse_money_string(str(PG_BIGINT_MAX)) == PG_BIGINT_MAX
    assert parse_money_string("0" * 5000 + "2") == 2
    assert line_total(PG_BIGINT_MAX, 1) == PG_BIGINT_MAX
    with pytest.raises(ValueError):
        parse_money_string(str(PG_BIGINT_MAX + 1))
    with pytest.raises(ValueError):
        parse_money_string("9" * 5000)


@pytest.mark.parametrize(
    "lines,shipping",
    [
        ([(PG_BIGINT_MAX, 2)], 0),
        ([(PG_BIGINT_MAX, 1), (1, 1)], 0),
        ([(PG_BIGINT_MAX, 1)], 1),
        ([(1, 1)], PG_BIGINT_MAX + 1),
        ([(-1, 1)], 0),
        ([(True, 1)], 0),
        ([(1, 1)], False),
    ],
)
def test_every_amount_and_intermediate_sum_must_fit_bigint(lines, shipping):
    with pytest.raises(ValueError):
        calculate_totals(lines, shipping)


def test_order_line_limits_also_apply_to_generators():
    assert calculate_totals(((1, 1) for _ in range(50)), 0).total_amount == 50
    for lines in ([], ((1, 1) for _ in range(51))):
        with pytest.raises(ValueError):
            calculate_totals(lines, 0)
