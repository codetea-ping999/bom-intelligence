"""Deterministic extractor for native PowerPoint tables (no AI)."""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.shapes.graphfrm import GraphicFrame

from bom_intelligence.extractor.rows import ColumnSpec, GridCell, GridRow, build_records
from bom_intelligence.models.bom import BOMRecord, SourceReference
from bom_intelligence.models.diagnostics import (
    Diagnostic,
    FailureCode,
    Location,
    Observation,
    Severity,
    SuggestedStrategy,
)
from bom_intelligence.profiler.powerpoint import PowerPointProfile, TableHeader, _walk

PARSER_VERSION = "ppt-table/0.1.0"


def _usable(header: TableHeader) -> FailureCode | None:
    if len(header.columns_for("part_number")) != 1:
        return (
            FailureCode.MULTIPLE_PART_FIELDS
            if header.columns_for("part_number")
            else FailureCode.SEMANTIC_AMBIGUITY
        )
    if len(header.columns_for("cost")) > 1:
        return FailureCode.MULTIPLE_COST_FIELDS
    if len(header.columns_for("schedule")) > 1:
        return FailureCode.MULTIPLE_SCHEDULE_FIELDS
    for category in ("part_name", "supplier"):
        if len(header.columns_for(category)) > 1:
            return FailureCode.SEMANTIC_AMBIGUITY
    return None


def extract_ppt_tables(
    path: Path,
    profile: PowerPointProfile,
    *,
    file_label: str,
    file_sha256: str,
    blocking: list[Diagnostic] | None = None,
    warning_codes: list[str] | None = None,
) -> tuple[list[BOMRecord], list[Diagnostic], list[str]]:
    if profile.read_error is not None:
        return [], [], ["profile has read error"]
    if blocking:
        return [], list(blocking), ["blocked by profile diagnostics"]
    headers = [h for s in profile.slides for h in s.table_headers]
    refusals: list[Diagnostic] = []
    for header in headers:
        code = _usable(header)
        if code is not None:
            refusals.append(
                Diagnostic(
                    file=profile.file,
                    document_type=profile.document_type,
                    code=code,
                    severity=Severity.ERROR,
                    message="Table header is ambiguous; refusing to guess.",
                    suggested_strategy=SuggestedStrategy.SEMANTIC,
                    evidence=(
                        Observation(
                            location=Location(slide=header.slide, shape_id=header.shape_id)
                        ),
                    ),
                )
            )
    if refusals:
        return [], refusals, ["refused"]
    if not headers:
        return [], [], ["no table headers"]

    prs = Presentation(str(path))
    records: list[BOMRecord] = []
    notes: list[str] = []
    for header in headers:
        slide = prs.slides[header.slide - 1]
        frame = next(
            s
            for s, _ in _walk(slide.shapes)
            if s.shape_id == header.shape_id and isinstance(s, GraphicFrame)
        )
        table = frame.table

        def src(r: int, c: int, text: str | None, h: TableHeader = header) -> SourceReference:
            return SourceReference(
                filename=file_label,
                file_sha256=file_sha256,
                document_type=profile.document_type,
                slide=h.slide,
                shape_id=h.shape_id,
                table_cell=f"R{r}C{c}",
                original_text=text,
            )

        columns = [
            ColumnSpec(
                key=str(c.column),
                category=c.category,
                subtype=c.subtype,
                header=GridCell(raw=c.text, source=src(1, c.column, c.text)),
            )
            for c in header.columns
            if c.category is not None
        ]
        rows: list[GridRow] = []
        for r_index in range(1, len(table.rows)):
            cells: dict[str, GridCell] = {}
            for col in columns:
                c = int(col.key)
                text = table.cell(r_index, c - 1).text.strip() or None
                cells[col.key] = GridCell(raw=text, source=src(r_index + 1, c, text))
            rows.append(GridRow(cells=cells))
        built, skipped = build_records(
            columns, rows, parser_version=PARSER_VERSION, file_warnings=list(warning_codes or [])
        )
        records.extend(built)
        notes.extend(skipped)
    return records, [], notes
