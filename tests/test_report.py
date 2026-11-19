from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bom_intelligence.pipeline import DocumentResult, analyze_directory, read_results
from bom_intelligence.reporting import build_summary, complexity, write_report


@pytest.fixture(scope="module")
def run(
    fixture_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, list[DocumentResult]]:
    out = tmp_path_factory.mktemp("report-run")
    return out, analyze_directory(fixture_dir, out)


def test_summary_counts(run: tuple[Path, list[DocumentResult]]) -> None:
    _, results = run
    s = build_summary(results)
    assert s["documents"] == 19
    assert s["formats"] == {"pdf": 1, "pptx": 5, "xls": 1, "xlsx": 12}
    assert s["access"] == {"unreadable": 1, "password_protected": 1, "unsupported_format": 2}
    assert s["routing_buckets"] == {
        "deterministic": 6,
        "semantic_candidate": 7,
        "ocr_or_human": 4,
        "unsupported": 2,
    }
    assert str(s["headline"]).startswith("31.6% deterministic, 36.8% semantic candidate")
    det = s["deterministic"]
    assert isinstance(det, dict) and det["succeeded"] == 6 and det["records"] == 18


def test_structural_vs_semantic_separated(run: tuple[Path, list[DocumentResult]]) -> None:
    _, results = run
    groups = build_summary(results)["blocking_documents_by_group"]
    assert groups == {"access": 4, "structural": 5, "semantic": 3, "unknown": 1}


def test_complexity_exposes_factors(run: tuple[Path, list[DocumentResult]]) -> None:
    _, results = run
    by_path = {r.path: r for r in results}
    assert complexity(by_path["excel/clean_table.xlsx"]) == (0.0, [])
    score, factors = complexity(by_path["excel/multiple_tables.xlsx"])
    assert score == 2.5
    assert factors == ["multiple_tables+2", "shifted_layout+0.5"]
    score, factors = complexity(by_path["excel/corrupt.xlsx"])
    assert score is None and factors[0].startswith("not assessable")


def test_report_reproducible_from_stored_results(
    run: tuple[Path, list[DocumentResult]], tmp_path: Path
) -> None:
    out, results = run
    a = write_report(results, tmp_path / "a")
    b = write_report(read_results(out), tmp_path / "b")
    assert a == b
    assert (tmp_path / "a" / "report.md").read_text() == (tmp_path / "b" / "report.md").read_text()
    summary = json.loads((tmp_path / "a" / "summary.json").read_text(encoding="utf-8"))
    assert summary["documents"] == 19
    with (tmp_path / "a" / "documents.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 19
    assert {"complexity_score", "complexity_factors", "bucket"} <= set(rows[0])
    md = (tmp_path / "a" / "report.md").read_text(encoding="utf-8")
    assert "Structural vs semantic blockers" in md
    assert "% deterministic" in md
