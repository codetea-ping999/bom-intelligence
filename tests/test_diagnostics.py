from __future__ import annotations

from pathlib import Path

import pytest

from bom_intelligence.analyzer import diagnose_excel, diagnose_powerpoint, diagnose_unsupported
from bom_intelligence.models import (
    FAILURE_CODE_INFO,
    Diagnostic,
    DocumentType,
    FailureCode,
    Severity,
    SuggestedStrategy,
)
from bom_intelligence.profiler import profile_excel, profile_powerpoint

DOCS = Path(__file__).resolve().parents[1] / "docs" / "failure-codes.md"


def _codes(diags: list[Diagnostic]) -> set[FailureCode]:
    return {d.code for d in diags}


def _excel(fixture_dir: Path, name: str) -> list[Diagnostic]:
    return diagnose_excel(profile_excel(fixture_dir / "excel" / name))


def _ppt(fixture_dir: Path, name: str) -> list[Diagnostic]:
    return diagnose_powerpoint(profile_powerpoint(fixture_dir / "powerpoint" / name))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("clean_table.xlsx", set()),
        ("shifted_header.xlsx", {FailureCode.SHIFTED_LAYOUT}),
        ("merged_header.xlsx", {FailureCode.MERGED_LAYOUT}),
        ("multiple_tables.xlsx", {FailureCode.MULTIPLE_TABLES, FailureCode.SHIFTED_LAYOUT}),
        ("multiple_cost_fields.xlsx", {FailureCode.MULTIPLE_COST_FIELDS}),
        ("multiple_schedule_fields.xlsx", {FailureCode.MULTIPLE_SCHEDULE_FIELDS}),
        ("hidden_content.xlsx", {FailureCode.HIDDEN_CONTENT}),
        ("formula_values.xlsx", {FailureCode.FORMULA_DEPENDENCY}),
        ("no_header.xlsx", {FailureCode.HEADER_NOT_FOUND}),
        ("password_protected.xlsx", {FailureCode.PASSWORD_PROTECTED}),
        ("corrupt.xlsx", {FailureCode.UNREADABLE_FILE}),
    ],
)
def test_excel_failure_classes(fixture_dir: Path, name: str, expected: set[FailureCode]) -> None:
    assert _codes(_excel(fixture_dir, name)) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("native_table.pptx", set()),
        ("freeform_text.pptx", {FailureCode.FREEFORM_LAYOUT}),
        ("grouped_shapes.pptx", {FailureCode.FREEFORM_LAYOUT}),
        ("image_heavy.pptx", {FailureCode.IMAGE_ONLY}),
        ("embedded_object.pptx", {FailureCode.EMBEDDED_OBJECT, FailureCode.UNKNOWN}),
    ],
)
def test_ppt_failure_classes(fixture_dir: Path, name: str, expected: set[FailureCode]) -> None:
    assert _codes(_ppt(fixture_dir, name)) == expected


def test_unsupported_formats() -> None:
    (pdf,) = diagnose_unsupported("a.pdf", DocumentType.PDF)
    assert pdf.code is FailureCode.UNSUPPORTED_FORMAT
    assert pdf.suggested_strategy is SuggestedStrategy.OCR
    (xls,) = diagnose_unsupported("a.xls", DocumentType.XLS)
    assert xls.suggested_strategy is SuggestedStrategy.UNSUPPORTED


def test_multiple_diagnostics_on_one_file(fixture_dir: Path) -> None:
    diags = _excel(fixture_dir, "multiple_tables.xlsx")
    assert len(diags) >= 2
    assert {d.file for d in diags} == {"multiple_tables.xlsx"}


def test_warning_vs_error(fixture_dir: Path) -> None:
    (shifted,) = _excel(fixture_dir, "shifted_header.xlsx")
    assert shifted.severity is Severity.WARNING and not shifted.blocks_deterministic
    (merged,) = _excel(fixture_dir, "merged_header.xlsx")
    assert merged.severity is Severity.ERROR and merged.blocks_deterministic


def test_evidence_and_candidates_located(fixture_dir: Path) -> None:
    (cost,) = _excel(fixture_dir, "multiple_cost_fields.xlsx")
    assert [o.location.label() for o in cost.evidence] == ["BOM!C1", "BOM!D1"]
    (freeform,) = _ppt(fixture_dir, "freeform_text.pptx")
    assert {c.text for c in freeform.candidates} >= {"SYN-3001", "¥980"}
    (missing,) = _excel(fixture_dir, "no_header.xlsx")
    assert missing.candidates[0].location.label() == "BOM!B2"


def test_grouped_shapes_noted(fixture_dir: Path) -> None:
    (diag,) = _ppt(fixture_dir, "grouped_shapes.pptx")
    assert "grouped" in diag.message


def test_unknown_retains_evidence(fixture_dir: Path) -> None:
    unknown = next(d for d in _ppt(fixture_dir, "embedded_object.pptx") if d.code == "UNKNOWN")
    assert unknown.evidence
    assert "chart" in (unknown.evidence[0].text or "")


def test_header_variation(tmp_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Part No", "Unit Price per piece"])
    ws.append(["P-1", 3])
    path = tmp_path / "variation.xlsx"
    wb.save(path)
    diags = diagnose_excel(profile_excel(path))
    assert _codes(diags) == {FailureCode.HEADER_VARIATION}


def test_every_code_documented() -> None:
    text = DOCS.read_text(encoding="utf-8")
    for code in FailureCode:
        assert f"`{code.value}`" in text
        assert code in FAILURE_CODE_INFO
