"""Conservative value normalization.

Each parser returns ``None`` plus a warning rather than guessing when the input is
ambiguous. Original text is always kept by the caller.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_CURRENCY_MARKERS: tuple[tuple[str, str], ...] = (
    ("JPY", "JPY"),
    ("USD", "USD"),
    ("EUR", "EUR"),
    ("¥", "JPY"),
    ("円", "JPY"),
    ("$", "USD"),
    ("€", "EUR"),
)
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_YMD = re.compile(r"^(\d{4})\s*[/\-.年]\s*(\d{1,2})\s*[/\-.月]\s*(\d{1,2})\s*日?$")
_YM = re.compile(r"^(\d{4})\s*[/\-.年]\s*(\d{1,2})\s*月?$")


def detect_currency(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text).upper()
    found = {code for marker, code in _CURRENCY_MARKERS if marker.upper() in normalized}
    return found.pop() if len(found) == 1 else None


def parse_cost(raw: object, header_text: str = "") -> tuple[Decimal | None, str | None, list[str]]:
    """Return ``(value, currency, warnings)``."""
    currency = detect_currency(header_text) if header_text else None
    if isinstance(raw, bool) or raw is None:
        return None, currency, [] if raw is None else ["boolean in cost cell"]
    if isinstance(raw, int | float | Decimal):
        value = Decimal(str(raw))
        if not value.is_finite():
            return None, currency, ["non-finite cost"]
        return value, currency, []
    text = unicodedata.normalize("NFKC", str(raw)).strip()
    cell_currency = detect_currency(text)
    if cell_currency and currency and cell_currency != currency:
        return None, None, [f"currency conflict: header {currency}, cell {cell_currency}"]
    currency = cell_currency or currency
    stripped = re.sub(r"(JPY|USD|EUR|[¥$€円,\s])", "", text, flags=re.IGNORECASE)
    if _NUMBER.match(stripped):
        try:
            return Decimal(stripped), currency, []
        except InvalidOperation:  # pragma: no cover - regex guarantees validity
            pass
    return None, currency, [f"cost text is not a single number: {text!r}"]


def parse_schedule(
    raw: object,
) -> tuple[dt.date | None, tuple[dt.date, dt.date] | None, list[str]]:
    """Return ``(date, (range_start, range_end), warnings)``."""
    if raw is None:
        return None, None, []
    if isinstance(raw, dt.datetime):
        return raw.date(), None, []
    if isinstance(raw, dt.date):
        return raw, None, []
    if isinstance(raw, int | float):
        return None, None, [f"numeric schedule value {raw!r} is not a date"]
    text = unicodedata.normalize("NFKC", str(raw)).strip()
    if m := _YMD.match(text):
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])), None, []
        except ValueError:
            return None, None, [f"invalid calendar date: {text!r}"]
    if m := _YM.match(text):
        year, month = int(m[1]), int(m[2])
        if 1 <= month <= 12:
            last = calendar.monthrange(year, month)[1]
            return (
                None,
                (dt.date(year, month, 1), dt.date(year, month, last)),
                ["month-only schedule kept as a range"],
            )
    try:
        return dt.date.fromisoformat(text), None, []
    except ValueError:
        return None, None, [f"schedule text is not a date: {text!r}"]
