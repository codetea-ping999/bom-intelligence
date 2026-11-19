"""Deterministic Excel BOM extractor (no AI).

Works only when the profile shows an unambiguous table: one header row per sheet
with exactly one part-number column and at most one cost and schedule column.
Anything else is refused with diagnostics instead of guessed.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from openpyxl import load_workbook

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
from bom_intelligence.profiler.common import range_bounds
from bom_intelligence.profiler.excel import ExcelProfile, HeaderCandidate, SheetProfile

PARSER_VERSION = "excel-table/0.1.0"
SINGLE_VALUE_CATEGORIES = ("part_number", "part_name", "supplier", "cost", "schedule")


class ExtractionRefused(Exception):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.code.value for d in diagnostics))
        self.diagnostics = diagnostics


def _refusal(
    profile: ExcelProfile, code: FailureCode, message: str, evidence: list[Observation]
) -> Diagnostic:
    return Diagnostic(
        file=profile.file,
        document_type=profile.document_type,
        code=code,
        severity=Severity.ERROR,
        message=message,
        suggested_strategy=SuggestedStrategy.SEMANTIC,
        evidence=tuple(evidence),
    )


def _select_tables(profile: ExcelProfile) -> list[tuple[SheetProfile, HeaderCandidate]]:
    selected: list[tuple[SheetProfile, HeaderCandidate]] = []
    problems: list[Diagnostic] = []
    for sheet in profile.visible_sheets():
        if not sheet.header_candidates:
            continue
        if len(sheet.header_candidates) > 1:
            problems.append(
                _refusal(
                    profile,
                    FailureCode.MULTIPLE_TABLES,
                    f"Competing header rows in sheet '{sheet.name}'.",
                    [
                        Observation(location=Location(sheet=sheet.name, cell_range=h.range))
                        for h in sheet.header_candidates
                    ],
                )
            )
            continue
        header = sheet.header_candidates[0]
        if len(header.columns_for("part_number")) != 1:
            problems.append(
                _refusal(
                    profile,
                    FailureCode.MULTIPLE_PART_FIELDS
                    if header.columns_for("part_number")
                    else FailureCode.SEMANTIC_AMBIGUITY,
                    "Header must have exactly one part-number column.",
                    [Observation(location=Location(sheet=sheet.name, cell_range=header.range))],
                )
            )
            continue
        for category in SINGLE_VALUE_CATEGORIES[1:]:
            if len(header.columns_for(category)) > 1:
                code = {
                    "cost": FailureCode.MULTIPLE_COST_FIELDS,
                    "schedule": FailureCode.MULTIPLE_SCHEDULE_FIELDS,
                }.get(category, FailureCode.SEMANTIC_AMBIGUITY)
                problems.append(
                    _refusal(
                        profile,
                        code,
                        f"Several '{category}' columns; refusing to guess.",
                        [
                            Observation(location=Location(sheet=sheet.name, cell_range=c.cell))
                            for c in header.columns_for(category)
                        ],
                    )
                )
                break
        else:
            selected.append((sheet, header))
    if problems:
        raise ExtractionRefused(problems)
    if not selected:
        raise ExtractionRefused(
            [_refusal(profile, FailureCode.HEADER_NOT_FOUND, "No usable header row.", [])]
        )
    return selected


def extract_excel(
    path: Path,
    profile: ExcelProfile,
    *,
    file_label: str,
    file_sha256: str,
    blocking: list[Diagnostic] | None = None,
    warning_codes: list[str] | None = None,
) -> tuple[list[BOMRecord], list[Diagnostic], list[str]]:
    """Return ``(records, diagnostics, notes)``; never guesses on ambiguity."""
    if profile.read_error is not None:
        return [], [], ["profile has read error"]
    if blocking:
        return [], list(blocking), ["blocked by profile diagnostics"]
    try:
        tables = _select_tables(profile)
    except ExtractionRefused as refused:
        return [], refused.diagnostics, ["refused"]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        values_wb = load_workbook(path, read_only=False, data_only=True, keep_vba=False)
        formula_wb = load_workbook(path, read_only=False, data_only=False, keep_vba=False)
    records: list[BOMRecord] = []
    diagnostics: list[Diagnostic] = []
    notes: list[str] = []
    try:
        for sheet, header in tables:
            region = next(
                r
                for r in sheet.table_regions
                if r.range.split(":")[0] == header.range.split(":")[0]
            )
            ws_values = values_wb[sheet.name]
            ws_formulas = formula_wb[sheet.name]

            def src(coord: str, text: str | None, sheet_name: str = sheet.name) -> SourceReference:
                return SourceReference(
                    filename=file_label,
                    file_sha256=file_sha256,
                    document_type=profile.document_type,
                    sheet=sheet_name,
                    cell_range=coord,
                    original_text=text,
                )

            columns = [
                ColumnSpec(
                    key=c.column,
                    category=c.category,
                    subtype=c.subtype,
                    header=GridCell(raw=c.text, source=src(c.cell, c.text)),
                )
                for c in header.columns
                if c.category is not None
            ]
            _, _, _, last_row = range_bounds(region.range)
            hidden_rows = set(sheet.hidden_rows)
            hidden_cols = set(sheet.hidden_columns)
            missing_cached: list[str] = []
            rows: list[GridRow] = []
            for r in range(header.row + 1, last_row + 1):
                cells: dict[str, GridCell] = {}
                row_warnings: list[str] = []
                for col in columns:
                    coord = f"{col.key}{r}"
                    raw = ws_values[coord].value
                    formula_cell = ws_formulas[coord]
                    if formula_cell.data_type == "f" and raw is None:
                        missing_cached.append(coord)
                        row_warnings.append(f"{coord}: formula without cached value")
                        if col.category in ("cost", "schedule"):
                            # Keep the expression as original text; the value stays unparsed.
                            raw = str(formula_cell.value)
                    text = None if raw is None else str(raw).strip() or None
                    if text is None and formula_cell.data_type == "f":
                        text = str(formula_cell.value)
                    cells[col.key] = GridCell(raw=raw, source=src(coord, text))
                    if col.key in hidden_cols and text is not None:
                        row_warnings.append(f"{coord}: value from hidden column")
                if r in hidden_rows:
                    row_warnings.append(f"row {r} is hidden in the source")
                rows.append(GridRow(cells=cells, warnings=row_warnings))
            built, skipped = build_records(
                columns,
                rows,
                parser_version=PARSER_VERSION,
                file_warnings=list(warning_codes or []),
            )
            records.extend(built)
            notes.extend(skipped)
            if missing_cached:
                diagnostics.append(
                    Diagnostic(
                        file=profile.file,
                        document_type=profile.document_type,
                        code=FailureCode.FORMULA_DEPENDENCY,
                        severity=Severity.WARNING,
                        message=(
                            f"{len(missing_cached)} formula cell(s) have no cached value; "
                            "values left empty. Recalculate and save in Excel to fix."
                        ),
                        suggested_strategy=SuggestedStrategy.HUMAN_REVIEW,
                        evidence=tuple(
                            Observation(location=Location(sheet=sheet.name, cell_range=c))
                            for c in missing_cached[:20]
                        ),
                    )
                )
    finally:
        values_wb.close()
        formula_wb.close()
    return records, diagnostics, notes
