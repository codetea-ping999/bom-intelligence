"""Structural Excel profiler (``.xlsx`` / ``.xlsm``) built on openpyxl.

Safety: workbooks are opened read-only in memory with ``keep_vba=False``; macros
are never evaluated and the file is never written.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from bom_intelligence.models.diagnostics import FailureCode
from bom_intelligence.models.document import document_type_for_suffix
from bom_intelligence.profiler.common import (
    KeywordHit,
    ProfileBase,
    ReadError,
    _Model,
    clip,
    detect_container_problem,
    range_bounds,
    ranges_intersect,
    zip_members,
)
from bom_intelligence.vocabulary import Vocabulary, default_vocabulary

MAX_KEYWORD_HITS_PER_SHEET = 200
MAX_FORMULA_SAMPLES = 500
MAX_HEADER_TEXT = 40

ExcelLayoutHint = Literal["regular_table", "multi_table", "layout", "image", "no_bom_content"]


class HeaderColumn(_Model):
    column: str
    cell: str
    text: str
    category: str | None
    subtype: str | None
    exact: bool


class HeaderCandidate(_Model):
    sheet: str
    row: int
    range: str
    columns: tuple[HeaderColumn, ...]

    def categories(self) -> list[str]:
        return [c.category for c in self.columns if c.category is not None]

    def columns_for(self, category: str) -> list[HeaderColumn]:
        return [c for c in self.columns if c.category == category]


class TableRegion(_Model):
    sheet: str
    range: str
    header_row: int
    data_rows: int
    formula_cells: int = 0
    formula_samples: tuple[str, ...] = ()


class SheetProfile(_Model):
    name: str
    index: int
    state: str
    used_range: str | None
    max_row: int
    max_column: int
    non_empty_cells: int
    density: float
    merged_ranges: tuple[str, ...]
    formula_cells: int
    formula_samples: tuple[str, ...]
    hidden_rows: tuple[int, ...]
    hidden_columns: tuple[str, ...]
    tables: tuple[str, ...]
    hyperlinks: int
    images: int
    charts: int
    keyword_hit_count: int
    keyword_hits: tuple[KeywordHit, ...]
    header_candidates: tuple[HeaderCandidate, ...]
    table_regions: tuple[TableRegion, ...]

    @property
    def hidden(self) -> bool:
        return self.state != "visible"


class ExcelProfile(ProfileBase):
    kind: Literal["excel"] = "excel"
    sheet_count: int = 0
    has_vba: bool = False
    defined_names: tuple[str, ...] = ()
    external_links: int = 0
    sheets: tuple[SheetProfile, ...] = ()
    layout_hint: ExcelLayoutHint = "no_bom_content"

    def visible_sheets(self) -> list[SheetProfile]:
        return [s for s in self.sheets if not s.hidden]

    def stats(self) -> dict[str, int | float]:
        return {
            "sheets": self.sheet_count,
            "hidden_sheets": sum(1 for s in self.sheets if s.hidden),
            "header_candidates": sum(len(s.header_candidates) for s in self.sheets),
            "merged_ranges": sum(len(s.merged_ranges) for s in self.sheets),
            "formula_cells": sum(s.formula_cells for s in self.sheets),
            "images": sum(s.images for s in self.sheets),
            "keyword_hits": sum(s.keyword_hit_count for s in self.sheets),
        }


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _merged_cover(ws: Worksheet) -> dict[tuple[int, int], str]:
    cover: dict[tuple[int, int], str] = {}
    for rng in ws.merged_cells.ranges:
        min_col, min_row, max_col, max_row = rng.bounds
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                cover[(r, c)] = rng.coord
    return cover


def _header_candidates(
    ws: Worksheet,
    values: dict[tuple[int, int], str],
    covered: dict[tuple[int, int], str],
    vocab: Vocabulary,
) -> list[HeaderCandidate]:
    candidates: list[HeaderCandidate] = []
    by_row: dict[int, list[int]] = {}
    for r, c in values:
        by_row.setdefault(r, []).append(c)
    for row in sorted(by_row):
        cols = sorted(by_row[row])
        # Segment the row into contiguous runs; merged-cell continuations count as filled.
        runs: list[list[int]] = []
        current: list[int] = []
        col = cols[0]
        while col <= cols[-1] or (row, col) in covered:
            if (row, col) in values or (row, col) in covered:
                current.append(col)
            elif current:
                runs.append(current)
                current = []
            col += 1
        if current:
            runs.append(current)
        for run in runs:
            columns: list[HeaderColumn] = []
            for col in run:
                text = values.get((row, col))
                if text is None:
                    continue
                letter = get_column_letter(col)
                match = vocab.match_header(text)
                if match is None and len(text) <= MAX_HEADER_TEXT:
                    found = vocab.find_keywords(text)
                    match = found[0] if len(found) == 1 else None
                columns.append(
                    HeaderColumn(
                        column=letter,
                        cell=f"{letter}{row}",
                        text=clip(text),
                        category=None if match is None else match.category.value,
                        subtype=None if match is None else match.subtype,
                        exact=False if match is None else match.exact,
                    )
                )
            categories = {c.category for c in columns if c.category is not None}
            if len(categories) >= 2:
                rng = f"{get_column_letter(run[0])}{row}:{get_column_letter(run[-1])}{row}"
                candidates.append(
                    HeaderCandidate(sheet=ws.title, row=row, range=rng, columns=tuple(columns))
                )
    return candidates


def _table_region(
    header: HeaderCandidate, values: dict[tuple[int, int], str], max_row: int
) -> TableRegion:
    bounds = range_boundaries(header.range)
    min_col, max_col = int(bounds[0] or 1), int(bounds[2] or 1)
    last = header.row
    for row in range(header.row + 1, max_row + 1):
        if any((row, c) in values for c in range(min_col, max_col + 1)):
            last = row
        else:
            break
    rng = f"{get_column_letter(min_col)}{header.row}:{get_column_letter(max_col)}{last}"
    return TableRegion(
        sheet=header.sheet, range=rng, header_row=header.row, data_rows=last - header.row
    )


def _with_formulas(region: TableRegion, formula_coords: list[tuple[int, int, str]]) -> TableRegion:
    min_col, min_row, max_col, max_row = range_bounds(region.range)
    inside = [
        coord
        for r, c, coord in formula_coords
        if min_row <= r <= max_row and min_col <= c <= max_col
    ]
    return region.model_copy(
        update={"formula_cells": len(inside), "formula_samples": tuple(inside[:20])}
    )


def _profile_sheet(ws: Worksheet, index: int, vocab: Vocabulary) -> SheetProfile:
    values: dict[tuple[int, int], str] = {}
    formula_cells = 0
    formula_samples: list[str] = []
    formula_coords: list[tuple[int, int, str]] = []
    hyperlinks = 0
    hits: list[KeywordHit] = []
    hit_count = 0
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell, MergedCell) or not isinstance(cell, Cell):
                continue
            if cell.hyperlink is not None:
                hyperlinks += 1
            if cell.data_type == "f":
                formula_cells += 1
                formula_coords.append((cell.row, cell.column, cell.coordinate))
                if len(formula_samples) < MAX_FORMULA_SAMPLES:
                    formula_samples.append(cell.coordinate)
            text = _text(cell.value)
            if text is None:
                continue
            values[(cell.row, cell.column)] = text
            if cell.data_type == "s":
                for match in vocab.find_keywords(text):
                    hit_count += 1
                    if len(hits) < MAX_KEYWORD_HITS_PER_SHEET:
                        hits.append(
                            KeywordHit(
                                category=match.category.value,
                                alias=match.alias,
                                exact=match.exact,
                                text=clip(text),
                                sheet=ws.title,
                                cell=cell.coordinate,
                            )
                        )
    covered = _merged_cover(ws)
    headers = _header_candidates(ws, values, covered, vocab)
    regions = [
        _with_formulas(_table_region(h, values, ws.max_row), formula_coords) for h in headers
    ]

    hidden_rows = sorted(r for r, dim in ws.row_dimensions.items() if dim.hidden)
    hidden_cols: list[str] = []
    for dim in ws.column_dimensions.values():
        if dim.hidden and dim.min is not None and dim.max is not None:
            hidden_cols.extend(get_column_letter(c) for c in range(dim.min, dim.max + 1))

    has_content = bool(values)
    max_row = ws.max_row if has_content else 0
    max_col = ws.max_column if has_content else 0
    area = max_row * max_col
    return SheetProfile(
        name=ws.title,
        index=index,
        state=ws.sheet_state,
        used_range=ws.dimensions if has_content else None,
        max_row=max_row,
        max_column=max_col,
        non_empty_cells=len(values),
        density=round(len(values) / area, 4) if area else 0.0,
        merged_ranges=tuple(sorted(r.coord for r in ws.merged_cells.ranges)),
        formula_cells=formula_cells,
        formula_samples=tuple(formula_samples),
        hidden_rows=tuple(hidden_rows),
        hidden_columns=tuple(sorted(set(hidden_cols), key=lambda s: (len(s), s))),
        tables=tuple(sorted(f"{tbl.name}={tbl.ref}" for tbl in ws.tables.values())),
        hyperlinks=hyperlinks,
        images=len(getattr(ws, "_images", [])),
        charts=len(getattr(ws, "_charts", [])),
        keyword_hit_count=hit_count,
        keyword_hits=tuple(hits),
        header_candidates=tuple(headers),
        table_regions=tuple(regions),
    )


def _layout_hint(sheets: list[SheetProfile]) -> ExcelLayoutHint:
    visible = [s for s in sheets if not s.hidden]
    headers = sum(len(s.header_candidates) for s in visible)
    if headers == 1:
        region = next(r for s in visible for r in s.table_regions)
        sheet = next(s for s in visible if s.table_regions)
        if any(ranges_intersect(m, region.range) for m in sheet.merged_ranges):
            return "layout"
        return "regular_table"
    if headers > 1:
        return "multi_table"
    if any(s.keyword_hit_count for s in visible):
        return "layout"
    if any(s.images for s in visible) and not any(s.non_empty_cells for s in visible):
        return "image"
    return "no_bom_content"


def profile_excel(
    path: Path, *, display_name: str | None = None, vocabulary: Vocabulary | None = None
) -> ExcelProfile:
    """Profile a workbook. Never raises for bad input; errors land in ``read_error``."""
    vocab = vocabulary or default_vocabulary()
    name = display_name or path.name
    doc_type = document_type_for_suffix(path.suffix)
    problem = detect_container_problem(path)
    if problem is not None:
        return ExcelProfile(file=name, document_type=doc_type, read_error=problem)
    try:
        members = zip_members(path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = load_workbook(
                path, read_only=False, keep_vba=False, data_only=False, keep_links=True
            )
    except Exception as exc:  # openpyxl raises many types for malformed packages
        return ExcelProfile(
            file=name,
            document_type=doc_type,
            read_error=ReadError(
                code=FailureCode.UNREADABLE_FILE, message=f"{type(exc).__name__}: {exc}"
            ),
        )
    try:
        sheets = [_profile_sheet(ws, i, vocab) for i, ws in enumerate(wb.worksheets)]
        return ExcelProfile(
            file=name,
            document_type=doc_type,
            sheet_count=len(sheets),
            has_vba="xl/vbaProject.bin" in members,
            defined_names=tuple(sorted(str(n) for n in wb.defined_names)),
            external_links=len(getattr(wb, "_external_links", [])),
            sheets=tuple(sheets),
            layout_hint=_layout_hint(sheets),
        )
    finally:
        wb.close()
