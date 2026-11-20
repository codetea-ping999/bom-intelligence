from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from bom_intelligence.cli import main
from bom_intelligence.evaluation import evaluate, load_gold
from bom_intelligence.pipeline import DocumentResult, analyze_directory
from bom_intelligence.synthetic import CLEAN_ROWS, FIXTURES

ROOT = Path(__file__).resolve().parent
GOLD = ROOT / "fixtures" / "gold"
BASELINE = ROOT / "fixtures" / "baseline_metrics.json"


@pytest.fixture(scope="module")
def run(
    fixture_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, list[DocumentResult]]:
    out = tmp_path_factory.mktemp("eval-run")
    return out, analyze_directory(fixture_dir, out)


def test_gold_covers_every_fixture() -> None:
    gold = load_gold(GOLD)
    assert len(gold) >= 15
    assert {g.path for g in gold} == set(FIXTURES)


def test_gold_clean_records_match_fixture_source_of_truth() -> None:
    """Gold values are checked against the generator, not against extractor output."""
    gold = {g.path: g for g in load_gold(GOLD)}
    for path in (
        "excel/clean_table.xlsx",
        "excel/shifted_header.xlsx",
        "powerpoint/native_table.pptx",
    ):
        records = gold[path].records
        assert [r.part_number for r in records] == [row[0] for row in CLEAN_ROWS]
        assert [Decimal(r.cost_value or "nan") for r in records] == [
            Decimal(str(row[2])) for row in CLEAN_ROWS
        ]
        assert all(r.cost_value and "E" not in r.cost_value for r in records)
        assert [r.schedule_date for r in records] == [row[3].isoformat() for row in CLEAN_ROWS]


def test_metrics_match_tracked_baseline(run: tuple[Path, list[DocumentResult]]) -> None:
    _, results = run
    metrics = evaluate(results, load_gold(GOLD))
    summary = {k: v for k, v in metrics.items() if k != "details"}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert summary == baseline, "extraction behaviour changed; update gold/baseline deliberately"


def test_regression_changes_metric(run: tuple[Path, list[DocumentResult]]) -> None:
    _, results = run
    broken = [
        r.model_copy(update={"records": r.records[1:]}) if r.path == "excel/clean_table.xlsx" else r
        for r in results
    ]
    metrics = evaluate(broken, load_gold(GOLD))
    assert metrics["record_recall"] != 1.0
    assert metrics["document_success_rate"] != 1.0


def test_cli_evaluate_and_report(run: tuple[Path, list[DocumentResult]], tmp_path: Path) -> None:
    out, _ = run
    metrics_path = tmp_path / "metrics.json"
    assert main(["evaluate", str(out), "--gold", str(GOLD), "-o", str(metrics_path)]) == 0
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["documents"] == len(FIXTURES)
    assert len(metrics["details"]) == len(FIXTURES)
    report_dir = tmp_path / "report"
    assert main(["report", str(out), "--metrics", str(metrics_path), "-o", str(report_dir)]) == 0
    for name in ("summary.json", "documents.csv", "diagnostics.csv", "report.md"):
        assert (report_dir / name).exists()
