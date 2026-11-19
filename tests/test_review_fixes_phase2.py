"""Regression tests for review findings on the Phase 2 PR."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from bom_intelligence.evaluation import GoldDocument, GoldRecord, evaluate
from bom_intelligence.evaluation.harness import record_to_gold
from bom_intelligence.extractor.normalize import parse_cost, parse_schedule
from bom_intelligence.pipeline import RouteStrategy, analyze_directory


@pytest.mark.parametrize("raw", ["€12,50", "1.234,56", "12,5", "1,23,456"])
def test_ambiguous_separators_refused(raw: str) -> None:
    value, _, warnings = parse_cost(raw)
    assert value is None and warnings


@pytest.mark.parametrize("raw", ["0000/04", "0000年4月"])
def test_invalid_month_only_year_does_not_raise(raw: str) -> None:
    date, rng, warnings = parse_schedule(raw)
    assert date is None and rng is None and warnings


def test_one_clean_table_per_sheet_is_deterministic(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Part No", "Unit Price"])
    ws.append(["A-1", 1])
    ws2 = wb.create_sheet("second")
    ws2.append(["Part No", "Unit Price"])
    ws2.append(["B-1", 2])
    wb.save(docs / "two.xlsx")
    (result,) = analyze_directory(docs, tmp_path / "out")
    assert result.decision.strategy is RouteStrategy.DETERMINISTIC_EXCEL
    assert [r.part.part_number for r in result.records] == ["A-1", "B-1"]


def test_output_dir_inside_input_is_not_rescanned(tmp_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Part No", "Unit Price"])
    ws.append(["A-1", 1])
    wb.save(tmp_path / "one.xlsx")
    first = analyze_directory(tmp_path, tmp_path / "out")
    second = analyze_directory(tmp_path, tmp_path / "out")
    assert [r.path for r in first] == [r.path for r in second] == ["one.xlsx"]


def test_uncached_formula_never_becomes_part_number(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Part No", "Part Name", "Unit Price"])
    ws.append(["=Other!A2", "=Other!B2", 5])
    ws.append(["P-2", "Plain", 6])
    wb.save(docs / "f.xlsx")
    (result,) = analyze_directory(docs, tmp_path / "out")
    assert [r.part.part_number for r in result.records] == ["P-2"]
    assert any("without part number" in n for n in result.extraction_notes)


def test_repeated_part_numbers_matched_one_to_one(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Part No", "Unit Price"])
    ws.append(["DUP", 1])
    ws.append(["DUP", 2])
    wb.save(docs / "dup.xlsx")
    results = analyze_directory(docs, tmp_path / "out")
    gold = GoldDocument(
        path="dup.xlsx",
        expected_strategy="deterministic_excel",
        records=tuple(record_to_gold(r) for r in reversed(results[0].records)),
    )
    assert all(isinstance(r, GoldRecord) for r in gold.records)
    metrics = evaluate(results, [gold])
    assert metrics["record_precision"] == 1.0
    assert metrics["record_recall"] == 1.0
    assert metrics["document_success_rate"] == 1.0
