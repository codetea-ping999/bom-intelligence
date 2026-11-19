from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from bom_intelligence.extractor.normalize import parse_cost, parse_schedule


@pytest.mark.parametrize(
    ("raw", "header", "value", "currency"),
    [
        (1250.5, "", Decimal("1250.5"), None),
        (12, "単価(円)", Decimal("12"), "JPY"),
        ("¥1,250.50", "", Decimal("1250.50"), "JPY"),
        ("$15.20", "", Decimal("15.20"), "USD"),
        ("1,200円", "", Decimal("1200"), "JPY"),
        ("ＵＳＤ 3", "", Decimal("3"), "USD"),
    ],
)
def test_parse_cost_ok(raw: object, header: str, value: Decimal, currency: str | None) -> None:
    got, cur, warnings = parse_cost(raw, header)
    assert (got, cur, warnings) == (value, currency, [])


@pytest.mark.parametrize("raw", ["約1,200〜1,500円", "TBD", "=A1*2", True])
def test_parse_cost_refuses_ambiguous(raw: object) -> None:
    value, _, warnings = parse_cost(raw)
    assert value is None
    assert warnings


def test_parse_cost_currency_conflict() -> None:
    value, currency, warnings = parse_cost("$5", "単価(円)")
    assert value is None and currency is None and "conflict" in warnings[0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (dt.datetime(2027, 4, 1, 9, 0), dt.date(2027, 4, 1)),
        (dt.date(2027, 4, 1), dt.date(2027, 4, 1)),
        ("2027/04/01", dt.date(2027, 4, 1)),
        ("2027-4-1", dt.date(2027, 4, 1)),
        ("2027年4月1日", dt.date(2027, 4, 1)),
    ],
)
def test_parse_schedule_dates(raw: object, expected: dt.date) -> None:
    assert parse_schedule(raw) == (expected, None, [])


def test_parse_schedule_month_is_range() -> None:
    date, rng, warnings = parse_schedule("2027年2月")
    assert date is None
    assert rng == (dt.date(2027, 2, 1), dt.date(2027, 2, 28))
    assert warnings


@pytest.mark.parametrize("raw", ["2027/02/30", "来春予定", 45000])
def test_parse_schedule_refuses(raw: object) -> None:
    date, rng, warnings = parse_schedule(raw)
    assert date is None and rng is None and warnings
