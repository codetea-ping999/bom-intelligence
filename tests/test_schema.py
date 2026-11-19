from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from bom_intelligence.models import (
    BOMRecord,
    CostInfo,
    DocumentType,
    ExtractionMetadata,
    ExtractionMethod,
    PartIdentity,
    ScheduleInfo,
    SourceReference,
    document_type_for_suffix,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples"
SHA = "a" * 64


def _src(**kw: object) -> SourceReference:
    base: dict[str, object] = {
        "filename": "x.xlsx",
        "file_sha256": SHA,
        "document_type": DocumentType.XLSX,
        "sheet": "BOM",
        "cell_range": "B3",
    }
    base.update(kw)
    return SourceReference.model_validate(base)


@pytest.mark.parametrize("name", ["clean_record.json", "ambiguous_record.json"])
def test_example_round_trip(name: str) -> None:
    raw = (EXAMPLES / name).read_text(encoding="utf-8")
    record = BOMRecord.from_json(raw)
    again = BOMRecord.from_json(record.to_json())
    assert again == record
    assert record.to_json() == again.to_json()


def test_clean_example_points_to_exact_source() -> None:
    record = BOMRecord.from_json((EXAMPLES / "clean_record.json").read_text(encoding="utf-8"))
    assert record.part.source is not None
    assert record.part.source.sheet == "BOM"
    assert record.part.source.cell_range == "A2"
    assert record.costs[0].value == Decimal("1250.50")
    assert record.costs[0].source is not None
    assert record.costs[0].source.cell_range == "C2"
    assert record.schedules[0].date == dt.date(2027, 4, 1)


def test_ambiguous_example_keeps_original_text() -> None:
    record = BOMRecord.from_json((EXAMPLES / "ambiguous_record.json").read_text(encoding="utf-8"))
    assert record.costs[0].value is None
    assert "1,200" in record.costs[0].original_text
    assert record.metadata.warnings


def test_serialization_is_deterministic() -> None:
    record = BOMRecord(
        part=PartIdentity(part_number="P-1", source=_src()),
        costs=(CostInfo(value=Decimal("10"), original_text="10", currency="USD"),),
        metadata=ExtractionMetadata(
            method=ExtractionMethod.DETERMINISTIC, confidence=1.0, parser_version="t/1"
        ),
    )
    assert record.to_json() == record.to_json()
    assert BOMRecord.from_json(record.to_json()) == record


@pytest.mark.parametrize("currency", ["yen", "JP", "JPYY", "jpy", "12A"])
def test_invalid_currency_rejected(currency: str) -> None:
    with pytest.raises(ValidationError):
        CostInfo(value=Decimal("1"), original_text="1", currency=currency)


def test_non_finite_cost_rejected() -> None:
    with pytest.raises(ValidationError):
        CostInfo(value=Decimal("NaN"), original_text="?")


@pytest.mark.parametrize("confidence", [-0.1, 1.01, 5])
def test_invalid_confidence_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        ExtractionMetadata(
            method=ExtractionMethod.DETERMINISTIC, confidence=confidence, parser_version="t"
        )


def test_invalid_date_rejected() -> None:
    with pytest.raises(ValidationError):
        ScheduleInfo.model_validate({"date": "2027-02-30", "original_text": "2/30"})


def test_reversed_range_rejected() -> None:
    with pytest.raises(ValidationError):
        ScheduleInfo(
            range_start=dt.date(2027, 5, 1), range_end=dt.date(2027, 4, 1), original_text="x"
        )


def test_date_and_range_are_exclusive() -> None:
    with pytest.raises(ValidationError):
        ScheduleInfo(
            date=dt.date(2027, 1, 1),
            range_start=dt.date(2027, 1, 1),
            range_end=dt.date(2027, 2, 1),
            original_text="x",
        )


def test_half_range_rejected() -> None:
    with pytest.raises(ValidationError):
        ScheduleInfo(range_start=dt.date(2027, 1, 1), original_text="x")


@pytest.mark.parametrize("cell", ["A0", "1A", "A1:", "ABCD1", "a1"])
def test_invalid_cell_range_rejected(cell: str) -> None:
    with pytest.raises(ValidationError):
        _src(cell_range=cell)


def test_cell_range_requires_sheet() -> None:
    with pytest.raises(ValidationError):
        _src(sheet=None)


def test_shape_requires_slide_or_page() -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            filename="a.pptx", file_sha256=SHA, document_type=DocumentType.PPTX, shape_id=3
        )


def test_bad_hash_rejected() -> None:
    with pytest.raises(ValidationError):
        _src(file_sha256="xyz")


def test_empty_part_number_rejected() -> None:
    with pytest.raises(ValidationError):
        PartIdentity(part_number="   ")


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        PartIdentity.model_validate({"part_number": "P", "colour": "red"})


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (".XLSX", DocumentType.XLSX),
        ("xlsm", DocumentType.XLSM),
        (".jpeg", DocumentType.IMAGE),
        (".docx", DocumentType.OTHER),
        ("", DocumentType.OTHER),
    ],
)
def test_document_type_for_suffix(suffix: str, expected: DocumentType) -> None:
    assert document_type_for_suffix(suffix) is expected
