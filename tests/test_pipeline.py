from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bom_intelligence.models import DocumentType, FailureCode
from bom_intelligence.pipeline import (
    AdapterRegistry,
    DocumentExtractor,
    DocumentProfiler,
    DocumentRef,
    ExtractionResult,
    RouteStrategy,
    analyze_directory,
    default_registry,
    process_document,
    read_results,
    route,
)
from bom_intelligence.pipeline.adapters import (
    ExcelProfilerAdapter,
    ExcelTableExtractor,
    PowerPointProfilerAdapter,
)
from bom_intelligence.profiler.common import ProfileBase
from bom_intelligence.scanner import scan_directory
from bom_intelligence.synthetic import CLEAN_ROWS


@pytest.fixture(scope="module")
def results(fixture_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    out = tmp_path_factory.mktemp("run")
    return {r.path: r for r in analyze_directory(fixture_dir, out)} | {"__dir__": out}


def test_builtin_adapters_implement_contracts() -> None:
    assert isinstance(ExcelProfilerAdapter(), DocumentProfiler)
    assert isinstance(PowerPointProfilerAdapter(), DocumentProfiler)
    assert isinstance(ExcelTableExtractor(), DocumentExtractor)


@pytest.mark.parametrize(
    ("path", "strategy"),
    [
        ("excel/clean_table.xlsx", RouteStrategy.DETERMINISTIC_EXCEL),
        ("excel/shifted_header.xlsx", RouteStrategy.DETERMINISTIC_EXCEL),
        ("excel/merged_header.xlsx", RouteStrategy.SEMANTIC_TEXT),
        ("excel/multiple_cost_fields.xlsx", RouteStrategy.SEMANTIC_TEXT),
        ("excel/password_protected.xlsx", RouteStrategy.HUMAN_REVIEW),
        ("excel/corrupt.xlsx", RouteStrategy.UNSUPPORTED),
        ("excel/legacy.xls", RouteStrategy.UNSUPPORTED),
        ("other/scan.pdf", RouteStrategy.OCR),
        ("powerpoint/native_table.pptx", RouteStrategy.DETERMINISTIC_PPT_TABLE),
        ("powerpoint/freeform_text.pptx", RouteStrategy.SPATIAL_SEMANTIC),
        ("powerpoint/image_heavy.pptx", RouteStrategy.OCR),
        ("powerpoint/embedded_object.pptx", RouteStrategy.HUMAN_REVIEW),
    ],
)
def test_routing(results: dict[str, object], path: str, strategy: RouteStrategy) -> None:
    result = results[path]
    decision = result.decision  # type: ignore[attr-defined]
    assert decision.strategy is strategy
    assert decision.explanation


def test_router_reasons_carry_codes(results: dict[str, object]) -> None:
    decision = results["excel/merged_header.xlsx"].decision  # type: ignore[attr-defined]
    assert decision.reasons == (FailureCode.MERGED_LAYOUT,)
    assert "MERGED_LAYOUT" in decision.explanation


def test_unsupported_routes_without_profile() -> None:
    decision = route(DocumentType.OTHER, None, [])
    assert decision.strategy is RouteStrategy.UNSUPPORTED
    assert decision.reasons == (FailureCode.UNSUPPORTED_FORMAT,)


@pytest.mark.parametrize(
    "path", ["excel/clean_table.xlsx", "excel/shifted_header.xlsx", "excel/alias_variation.xlsx"]
)
def test_clean_excel_extraction(results: dict[str, object], path: str) -> None:
    records = results[path].records  # type: ignore[attr-defined]
    assert [r.part.part_number for r in records] == [row[0] for row in CLEAN_ROWS]
    assert [r.part.part_name for r in records] == [row[1] for row in CLEAN_ROWS]
    assert [r.costs[0].value for r in records] == [Decimal(str(row[2])) for row in CLEAN_ROWS]
    assert [r.schedules[0].date for r in records] == [row[3] for row in CLEAN_ROWS]
    assert all(r.metadata.method.value == "deterministic" for r in records)


def test_exact_cell_provenance(results: dict[str, object]) -> None:
    record = results["excel/shifted_header.xlsx"].records[0]  # type: ignore[attr-defined]
    assert record.part.source.sheet == "BOM"
    assert record.part.source.cell_range == "C6"
    assert record.costs[0].source.cell_range == "E6"
    assert record.schedules[0].source.cell_range == "F6"
    assert record.part.source.filename == "excel/shifted_header.xlsx"
    assert len(record.part.source.file_sha256) == 64
    assert [e.source.cell_range for e in record.metadata.evidence] == ["C5", "D5", "E5", "F5"]


def test_alias_header_subtypes(results: dict[str, object]) -> None:
    record = results["excel/alias_variation.xlsx"].records[0]  # type: ignore[attr-defined]
    assert record.costs[0].currency == "JPY"
    assert record.costs[0].cost_type.value == "production"
    assert record.costs[0].original_text == "¥1,250.50"
    assert record.schedules[0].milestone_type.value == "delivery"


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("excel/merged_header.xlsx", FailureCode.MERGED_LAYOUT),
        ("excel/multiple_tables.xlsx", FailureCode.MULTIPLE_TABLES),
        ("excel/multiple_cost_fields.xlsx", FailureCode.MULTIPLE_COST_FIELDS),
        ("excel/multiple_schedule_fields.xlsx", FailureCode.MULTIPLE_SCHEDULE_FIELDS),
        ("excel/no_header.xlsx", FailureCode.HEADER_NOT_FOUND),
    ],
)
def test_ambiguous_fixtures_fail_safely(
    results: dict[str, object], path: str, code: FailureCode
) -> None:
    result = results[path]
    assert result.records == ()  # type: ignore[attr-defined]
    assert code in {d.code for d in result.diagnostics}  # type: ignore[attr-defined]


def test_extractor_refuses_when_called_directly(fixture_dir: Path) -> None:
    entry = next(
        e for e in scan_directory(fixture_dir) if e.path == "excel/multiple_cost_fields.xlsx"
    )
    ref = DocumentRef(
        path=fixture_dir / entry.path,
        relative_path=entry.path,
        sha256=entry.sha256,
        document_type=entry.document_type,
    )
    adapter = ExcelProfilerAdapter()
    result = ExcelTableExtractor().extract(ref, adapter.profile(ref))
    assert result.records == ()
    assert {d.code for d in result.diagnostics} == {FailureCode.MULTIPLE_COST_FIELDS}


def test_formula_without_cache_keeps_formula(results: dict[str, object]) -> None:
    record = results["excel/formula_values.xlsx"].records[0]  # type: ignore[attr-defined]
    assert record.costs[0].value is None
    assert record.costs[0].original_text.startswith("=")
    assert any("formula" in w for w in record.metadata.warnings)
    assert record.metadata.confidence < 0.95


def test_ppt_table_provenance(results: dict[str, object]) -> None:
    record = results["powerpoint/native_table.pptx"].records[0]  # type: ignore[attr-defined]
    assert record.part.source.slide == 1
    assert record.part.source.table_cell == "R2C1"
    assert record.costs[0].source.table_cell == "R2C3"


def test_results_round_trip(results: dict[str, object]) -> None:
    out = results["__dir__"]
    assert isinstance(out, Path)
    reread = {r.path: r for r in read_results(out)}
    for path, result in results.items():
        if path != "__dir__":
            assert reread[path] == result
    assert (out / "records.jsonl").read_text(encoding="utf-8").count("\n") == 18


def test_crash_in_one_document_does_not_stop_batch(fixture_dir: Path, tmp_path: Path) -> None:
    class Exploding:
        name = "exploding"

        def supports(self, document: DocumentRef) -> bool:
            return document.document_type is DocumentType.PPTX

        def profile(self, document: DocumentRef) -> ProfileBase:
            raise RuntimeError("boom")

        def diagnose(self, profile: ProfileBase) -> list[object]:
            return []

    registry = default_registry()
    registry.profilers.insert(0, Exploding())  # type: ignore[arg-type]
    results = analyze_directory(fixture_dir, tmp_path)
    del results
    entries = scan_directory(fixture_dir)
    outcome = [process_document(fixture_dir.resolve(), e, registry) for e in entries]
    crashed = [r for r in outcome if r.document_type is DocumentType.PPTX]
    assert crashed and all(r.diagnostics[0].code is FailureCode.UNKNOWN for r in crashed)
    assert any(r.records for r in outcome if r.document_type is DocumentType.XLSX)


def test_new_fake_adapter_without_core_changes(tmp_path: Path) -> None:
    """A CSV adapter plugs in through the registry; models stay untouched."""
    from bom_intelligence.models import (
        BOMRecord,
        ExtractionMetadata,
        ExtractionMethod,
        PartIdentity,
        SourceReference,
    )

    class CsvProfile(ProfileBase):
        kind: str = "csv"
        rows: int = 0

    class CsvProfiler:
        name = "csv-profiler"

        def supports(self, document: DocumentRef) -> bool:
            return document.relative_path.endswith(".csv")

        def profile(self, document: DocumentRef) -> ProfileBase:
            rows = document.path.read_text().splitlines()
            return CsvProfile(
                file=document.relative_path,
                document_type=document.document_type,
                rows=len(rows),
                layout_hint="regular_table",
            )

        def diagnose(self, profile: ProfileBase) -> list[object]:
            return []

    class CsvExtractor:
        name = "csv"
        strategy = RouteStrategy.HUMAN_REVIEW

        def supports(self, document: DocumentRef) -> bool:
            return document.relative_path.endswith(".csv")

        def extract(self, document: DocumentRef, profile: ProfileBase) -> ExtractionResult:
            assert document.sha256 is not None
            pn = document.path.read_text().splitlines()[1]
            src = SourceReference(
                filename=document.relative_path,
                file_sha256=document.sha256,
                document_type=document.document_type,
                original_text=pn,
            )
            record = BOMRecord(
                part=PartIdentity(part_number=pn, source=src),
                metadata=ExtractionMetadata(
                    method=ExtractionMethod.DETERMINISTIC, confidence=1, parser_version="csv/0"
                ),
            )
            return ExtractionResult(extractor=self.name, records=(record,))

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "bom.csv").write_text("part_number\nCSV-1\n")
    registry = AdapterRegistry(profilers=[CsvProfiler()], extractors=[CsvExtractor()])  # type: ignore[list-item]
    (result,) = analyze_directory(tmp_path / "docs", tmp_path / "out", registry)
    assert result.profiler == "csv-profiler"
    assert result.profile_kind == "csv"
    assert [r.part.part_number for r in result.records] == ["CSV-1"]
