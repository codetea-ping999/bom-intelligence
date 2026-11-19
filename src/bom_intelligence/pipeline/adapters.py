"""Built-in adapters wrapping the Excel and PowerPoint profilers/extractors."""

from __future__ import annotations

from bom_intelligence.analyzer.diagnose import diagnose_excel, diagnose_powerpoint
from bom_intelligence.extractor.excel import extract_excel
from bom_intelligence.extractor.powerpoint import extract_ppt_tables
from bom_intelligence.models.diagnostics import Diagnostic, Severity
from bom_intelligence.models.document import DocumentType
from bom_intelligence.pipeline.contracts import (
    AdapterRegistry,
    DocumentRef,
    ExtractionResult,
    RouteStrategy,
)
from bom_intelligence.profiler.common import ProfileBase
from bom_intelligence.profiler.excel import ExcelProfile, profile_excel
from bom_intelligence.profiler.powerpoint import PowerPointProfile, profile_powerpoint
from bom_intelligence.vocabulary import Vocabulary

_EXCEL_TYPES = frozenset({DocumentType.XLSX, DocumentType.XLSM})


def _split(diagnostics: list[Diagnostic]) -> tuple[list[Diagnostic], list[str]]:
    blocking = [d for d in diagnostics if d.severity is Severity.ERROR]
    warnings = sorted({d.code.value for d in diagnostics if d.severity is not Severity.ERROR})
    return blocking, warnings


class ExcelProfilerAdapter:
    name = "excel-profiler"

    def __init__(self, vocabulary: Vocabulary | None = None) -> None:
        self.vocabulary = vocabulary

    def supports(self, document: DocumentRef) -> bool:
        return document.document_type in _EXCEL_TYPES

    def profile(self, document: DocumentRef) -> ProfileBase:
        return profile_excel(
            document.path, display_name=document.relative_path, vocabulary=self.vocabulary
        )

    def diagnose(self, profile: ProfileBase) -> list[Diagnostic]:
        assert isinstance(profile, ExcelProfile)
        return diagnose_excel(profile)


class PowerPointProfilerAdapter:
    name = "powerpoint-profiler"

    def __init__(self, vocabulary: Vocabulary | None = None) -> None:
        self.vocabulary = vocabulary

    def supports(self, document: DocumentRef) -> bool:
        return document.document_type is DocumentType.PPTX

    def profile(self, document: DocumentRef) -> ProfileBase:
        return profile_powerpoint(
            document.path, display_name=document.relative_path, vocabulary=self.vocabulary
        )

    def diagnose(self, profile: ProfileBase) -> list[Diagnostic]:
        assert isinstance(profile, PowerPointProfile)
        return diagnose_powerpoint(profile)


class ExcelTableExtractor:
    name = "excel-table"
    strategy = RouteStrategy.DETERMINISTIC_EXCEL

    def supports(self, document: DocumentRef) -> bool:
        return document.document_type in _EXCEL_TYPES and document.sha256 is not None

    def extract(self, document: DocumentRef, profile: ProfileBase) -> ExtractionResult:
        assert isinstance(profile, ExcelProfile) and document.sha256 is not None
        blocking, warnings = _split(diagnose_excel(profile))
        records, diagnostics, notes = extract_excel(
            document.path,
            profile,
            file_label=document.relative_path,
            file_sha256=document.sha256,
            blocking=blocking,
            warning_codes=warnings,
        )
        return ExtractionResult(
            extractor=self.name,
            records=tuple(records),
            diagnostics=tuple(diagnostics),
            notes=tuple(notes),
        )


class PowerPointTableExtractor:
    name = "ppt-table"
    strategy = RouteStrategy.DETERMINISTIC_PPT_TABLE

    def supports(self, document: DocumentRef) -> bool:
        return document.document_type is DocumentType.PPTX and document.sha256 is not None

    def extract(self, document: DocumentRef, profile: ProfileBase) -> ExtractionResult:
        assert isinstance(profile, PowerPointProfile) and document.sha256 is not None
        blocking, warnings = _split(diagnose_powerpoint(profile))
        records, diagnostics, notes = extract_ppt_tables(
            document.path,
            profile,
            file_label=document.relative_path,
            file_sha256=document.sha256,
            blocking=blocking,
            warning_codes=warnings,
        )
        return ExtractionResult(
            extractor=self.name,
            records=tuple(records),
            diagnostics=tuple(diagnostics),
            notes=tuple(notes),
        )


def default_registry(vocabulary: Vocabulary | None = None) -> AdapterRegistry:
    return AdapterRegistry(
        profilers=[ExcelProfilerAdapter(vocabulary), PowerPointProfilerAdapter(vocabulary)],
        extractors=[ExcelTableExtractor(), PowerPointTableExtractor()],
    )
