"""Derive structured diagnostics from profiles, deterministically (no LLM)."""

from __future__ import annotations

from openpyxl.utils import column_index_from_string

from bom_intelligence.models.diagnostics import (
    Diagnostic,
    FailureCode,
    Location,
    Observation,
    Severity,
    SuggestedStrategy,
)
from bom_intelligence.models.document import DocumentType
from bom_intelligence.profiler.common import KeywordHit, ReadError, range_bounds, ranges_intersect
from bom_intelligence.profiler.excel import ExcelProfile, HeaderCandidate, SheetProfile
from bom_intelligence.profiler.powerpoint import PowerPointProfile, TableHeader

_MULTI_FIELD_CODES: dict[str, FailureCode] = {
    "part_number": FailureCode.MULTIPLE_PART_FIELDS,
    "cost": FailureCode.MULTIPLE_COST_FIELDS,
    "schedule": FailureCode.MULTIPLE_SCHEDULE_FIELDS,
}


def _read_error(file: str, doc_type: DocumentType, error: ReadError) -> Diagnostic:
    strategy = (
        SuggestedStrategy.HUMAN_REVIEW
        if error.code is FailureCode.PASSWORD_PROTECTED
        else SuggestedStrategy.UNSUPPORTED
    )
    return Diagnostic(
        file=file,
        document_type=doc_type,
        code=error.code,
        severity=Severity.ERROR,
        message=error.message,
        suggested_strategy=strategy,
    )


def diagnose_unsupported(file: str, doc_type: DocumentType) -> list[Diagnostic]:
    if doc_type in (DocumentType.PDF, DocumentType.IMAGE):
        strategy = SuggestedStrategy.OCR
        message = f"No {doc_type.value} adapter yet; route to OCR/document adapter."
    elif doc_type in (DocumentType.XLS, DocumentType.PPT):
        strategy = SuggestedStrategy.UNSUPPORTED
        message = f"Legacy .{doc_type.value} needs conversion to OOXML before profiling."
    else:
        strategy = SuggestedStrategy.UNSUPPORTED
        message = "File type is not a BOM document format handled by this system."
    return [
        Diagnostic(
            file=file,
            document_type=doc_type,
            code=FailureCode.UNSUPPORTED_FORMAT,
            severity=Severity.ERROR,
            message=message,
            suggested_strategy=strategy,
        )
    ]


# --------------------------------------------------------------------------- Excel


def _cell(sheet: str, cell: str, text: str | None = None) -> Observation:
    return Observation(location=Location(sheet=sheet, cell_range=cell), text=text)


def _excel_header(
    profile: ExcelProfile, sheet: SheetProfile, header: HeaderCandidate
) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    start = header.range.split(":")[0]
    region = next(r for r in sheet.table_regions if r.range.split(":")[0] == start)

    def diag(
        code: FailureCode,
        severity: Severity,
        message: str,
        strategy: SuggestedStrategy,
        evidence: list[Observation],
    ) -> None:
        out.append(
            Diagnostic(
                file=profile.file,
                document_type=profile.document_type,
                code=code,
                severity=severity,
                message=message,
                suggested_strategy=strategy,
                evidence=tuple(evidence),
            )
        )

    min_col, min_row, _, _ = range_bounds(header.range)
    if (min_col, min_row) != (1, 1):
        diag(
            FailureCode.SHIFTED_LAYOUT,
            Severity.WARNING,
            f"Header starts at {header.range.split(':')[0]} instead of A1.",
            SuggestedStrategy.RULE,
            [_cell(sheet.name, header.range)],
        )
    if "part_number" not in header.categories():
        diag(
            FailureCode.SEMANTIC_AMBIGUITY,
            Severity.ERROR,
            "Header row has BOM-like labels but no part-number column.",
            SuggestedStrategy.SEMANTIC,
            [_cell(sheet.name, c.cell, c.text) for c in header.columns if c.category],
        )
    variants = [c for c in header.columns if c.category is not None and not c.exact]
    if variants:
        diag(
            FailureCode.HEADER_VARIATION,
            Severity.WARNING,
            "Some header labels only partially match known aliases.",
            SuggestedStrategy.SEMANTIC,
            [_cell(sheet.name, c.cell, c.text) for c in variants],
        )
    for category, code in _MULTI_FIELD_CODES.items():
        cols = header.columns_for(category)
        if len(cols) > 1:
            diag(
                code,
                Severity.ERROR,
                f"{len(cols)} columns look like '{category}'; cannot choose without context.",
                SuggestedStrategy.SEMANTIC,
                [_cell(sheet.name, c.cell, c.text) for c in cols],
            )
    merged = [m for m in sheet.merged_ranges if ranges_intersect(m, region.range)]
    if merged:
        diag(
            FailureCode.MERGED_LAYOUT,
            Severity.ERROR,
            f"{len(merged)} merged range(s) overlap the table {region.range}.",
            SuggestedStrategy.SEMANTIC,
            [_cell(sheet.name, m) for m in merged],
        )
    formulas = [f for f in sheet.formula_samples if ranges_intersect(f, region.range)]
    if formulas:
        diag(
            FailureCode.FORMULA_DEPENDENCY,
            Severity.WARNING,
            f"{len(formulas)} formula cell(s) inside the table; values rely on cached results.",
            SuggestedStrategy.RULE,
            [_cell(sheet.name, f) for f in formulas[:10]],
        )
    rmin_col, rmin_row, rmax_col, rmax_row = range_bounds(region.range)
    hidden_cols = [
        c for c in sheet.hidden_columns if rmin_col <= column_index_from_string(c) <= rmax_col
    ]
    hidden_rows = [r for r in sheet.hidden_rows if rmin_row <= r <= rmax_row]
    if hidden_cols or hidden_rows:
        evidence = [_cell(sheet.name, f"{c}{rmin_row}") for c in hidden_cols]
        evidence += [_cell(sheet.name, f"A{r}") for r in hidden_rows]
        diag(
            FailureCode.HIDDEN_CONTENT,
            Severity.WARNING,
            f"Table has {len(hidden_cols)} hidden column(s) and {len(hidden_rows)} hidden row(s).",
            SuggestedStrategy.RULE,
            evidence,
        )
    return out


def diagnose_excel(profile: ExcelProfile) -> list[Diagnostic]:
    if profile.read_error is not None:
        return [_read_error(profile.file, profile.document_type, profile.read_error)]
    out: list[Diagnostic] = []
    base = {"file": profile.file, "document_type": profile.document_type}
    if profile.external_links:
        out.append(
            Diagnostic(
                **base,
                code=FailureCode.EXTERNAL_LINK_DEPENDENCY,
                severity=Severity.WARNING,
                message=f"Workbook links to {profile.external_links} external workbook(s).",
                suggested_strategy=SuggestedStrategy.RULE,
            )
        )
    for sheet in profile.sheets:
        if sheet.hidden and (sheet.header_candidates or sheet.keyword_hit_count):
            out.append(
                Diagnostic(
                    **base,
                    code=FailureCode.HIDDEN_CONTENT,
                    severity=Severity.WARNING,
                    message=f"Hidden sheet '{sheet.name}' contains BOM-like content; ignored.",
                    suggested_strategy=SuggestedStrategy.HUMAN_REVIEW,
                    evidence=(Observation(location=Location(sheet=sheet.name)),),
                )
            )
    visible = profile.visible_sheets()
    for sheet in visible:
        if len(sheet.header_candidates) > 1:
            out.append(
                Diagnostic(
                    **base,
                    code=FailureCode.MULTIPLE_TABLES,
                    severity=Severity.ERROR,
                    message=(
                        f"Sheet '{sheet.name}' has {len(sheet.header_candidates)} candidate tables."
                    ),
                    suggested_strategy=SuggestedStrategy.SEMANTIC,
                    evidence=tuple(_cell(sheet.name, r.range) for r in sheet.table_regions),
                )
            )
        for header in sheet.header_candidates:
            out.extend(_excel_header(profile, sheet, header))
    if not any(s.header_candidates for s in visible):
        hits = [h for s in visible for h in s.keyword_hits]
        if hits:
            out.append(
                Diagnostic(
                    **base,
                    code=FailureCode.HEADER_NOT_FOUND,
                    severity=Severity.ERROR,
                    message="BOM keywords appear, but no header row/table was found.",
                    suggested_strategy=SuggestedStrategy.SEMANTIC,
                    candidates=tuple(
                        _cell(h.sheet or "", h.cell or "A1", h.text) for h in hits[:20]
                    ),
                )
            )
        elif any(s.images for s in visible):
            out.append(
                Diagnostic(
                    **base,
                    code=FailureCode.IMAGE_ONLY,
                    severity=Severity.ERROR,
                    message="Workbook content appears to be images without BOM text.",
                    suggested_strategy=SuggestedStrategy.OCR,
                )
            )
        else:
            out.append(_unknown(profile.file, profile.document_type, _excel_summary(profile)))
    return out


def _excel_summary(profile: ExcelProfile) -> list[Observation]:
    return [
        Observation(
            location=Location(sheet=s.name),
            text=(
                f"state={s.state} cells={s.non_empty_cells} merged={len(s.merged_ranges)} "
                f"formulas={s.formula_cells} images={s.images} charts={s.charts}"
            ),
        )
        for s in profile.sheets
    ]


def _unknown(file: str, doc_type: DocumentType, evidence: list[Observation]) -> Diagnostic:
    return Diagnostic(
        file=file,
        document_type=doc_type,
        code=FailureCode.UNKNOWN,
        severity=Severity.ERROR,
        message="No BOM content recognized; structural summary kept for taxonomy review.",
        suggested_strategy=SuggestedStrategy.HUMAN_REVIEW,
        evidence=tuple(evidence),
    )


# ---------------------------------------------------------------------- PowerPoint


def _shape(slide: int, shape_id: int, text: str | None = None) -> Observation:
    return Observation(location=Location(slide=slide, shape_id=shape_id), text=text)


def _ppt_table(profile: PowerPointProfile, header: TableHeader) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for category, code in _MULTI_FIELD_CODES.items():
        cols = header.columns_for(category)
        if len(cols) > 1:
            out.append(
                Diagnostic(
                    file=profile.file,
                    document_type=profile.document_type,
                    code=code,
                    severity=Severity.ERROR,
                    message=f"Table has {len(cols)} columns that look like '{category}'.",
                    suggested_strategy=SuggestedStrategy.SEMANTIC,
                    evidence=tuple(_shape(header.slide, header.shape_id, c.text) for c in cols),
                )
            )
    if not header.columns_for("part_number"):
        out.append(
            Diagnostic(
                file=profile.file,
                document_type=profile.document_type,
                code=FailureCode.SEMANTIC_AMBIGUITY,
                severity=Severity.ERROR,
                message="Table header has BOM-like labels but no part-number column.",
                suggested_strategy=SuggestedStrategy.SEMANTIC,
                evidence=(_shape(header.slide, header.shape_id),),
            )
        )
    return out


def diagnose_powerpoint(profile: PowerPointProfile) -> list[Diagnostic]:
    if profile.read_error is not None:
        return [_read_error(profile.file, profile.document_type, profile.read_error)]
    out: list[Diagnostic] = []
    base = {"file": profile.file, "document_type": profile.document_type}
    any_table_header = False
    freeform_hits: list[KeywordHit] = []
    for slide in profile.slides:
        oles = [s for s in slide.shapes if s.kind == "ole"]
        if oles:
            out.append(
                Diagnostic(
                    **base,
                    code=FailureCode.EMBEDDED_OBJECT,
                    severity=Severity.WARNING,
                    message=f"Slide {slide.number} has {len(oles)} embedded/OLE object(s).",
                    suggested_strategy=SuggestedStrategy.HUMAN_REVIEW,
                    evidence=tuple(_shape(slide.number, s.shape_id, s.name) for s in oles),
                )
            )
        if len(slide.table_headers) > 1:
            out.append(
                Diagnostic(
                    **base,
                    code=FailureCode.MULTIPLE_TABLES,
                    severity=Severity.ERROR,
                    message=f"Slide {slide.number} has {len(slide.table_headers)} BOM tables.",
                    suggested_strategy=SuggestedStrategy.SEMANTIC,
                    evidence=tuple(_shape(slide.number, h.shape_id) for h in slide.table_headers),
                )
            )
        for header in slide.table_headers:
            any_table_header = True
            out.extend(_ppt_table(profile, header))
        freeform_hits.extend(h for h in slide.keyword_hits if h.cell is None)
        for pair in slide.label_value_pairs:
            if pair.value_text is None:
                out.append(
                    Diagnostic(
                        **base,
                        code=FailureCode.SEMANTIC_AMBIGUITY,
                        severity=Severity.WARNING,
                        message=f"Label '{pair.label_text}' has no nearby value.",
                        suggested_strategy=SuggestedStrategy.SEMANTIC,
                        evidence=(_shape(slide.number, pair.label_shape_id, pair.label_text),),
                    )
                )
    if freeform_hits and not any_table_header:
        pairs = [p for s in profile.slides for p in s.label_value_pairs]
        grouped = {
            shape.shape_id
            for s in profile.slides
            for shape in s.shapes
            if shape.parent_group_id is not None
        }
        in_group = len([h for h in freeform_hits if h.shape_id in grouped])
        note = f" ({in_group} inside grouped shapes)" if in_group else ""
        out.append(
            Diagnostic(
                **base,
                code=FailureCode.FREEFORM_LAYOUT,
                severity=Severity.ERROR,
                message=f"{len(freeform_hits)} BOM label(s) in free-form text shapes{note}.",
                suggested_strategy=SuggestedStrategy.SEMANTIC,
                evidence=tuple(
                    _shape(h.slide or 0, h.shape_id or 0, h.text) for h in freeform_hits[:20]
                ),
                candidates=tuple(
                    _shape(p.slide, p.value_shape_id, p.value_text)
                    for p in pairs
                    if p.value_shape_id is not None
                ),
            )
        )
    has_hits = any(s.keyword_hits for s in profile.slides)
    if not has_hits:
        image_slides = [s for s in profile.slides if s.layout_hint == "image"]
        if image_slides:
            out.append(
                Diagnostic(
                    **base,
                    code=FailureCode.IMAGE_ONLY,
                    severity=Severity.ERROR,
                    message=f"{len(image_slides)} slide(s) are images without BOM text.",
                    suggested_strategy=SuggestedStrategy.OCR,
                    evidence=tuple(
                        Observation(
                            location=Location(slide=s.number),
                            text=f"picture_area_ratio={s.picture_area_ratio}",
                        )
                        for s in image_slides
                    ),
                )
            )
        else:
            out.append(
                _unknown(
                    profile.file,
                    profile.document_type,
                    [
                        Observation(
                            location=Location(slide=s.number),
                            text=f"shapes={s.shape_kinds} chars={s.text_characters}",
                        )
                        for s in profile.slides
                    ],
                )
            )
    return out
