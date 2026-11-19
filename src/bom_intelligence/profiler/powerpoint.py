"""Spatial PowerPoint profiler (``.pptx``) built on python-pptx.

Slides are treated as spatial documents: every text-bearing shape keeps its slide
number, shape id, and bounding box. PowerPoint is never launched and embedded
content is never executed; opaque objects are only recorded.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.shapes.base import BaseShape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.shapes.group import GroupShape
from pptx.shapes.picture import Picture

from bom_intelligence.models.diagnostics import FailureCode
from bom_intelligence.models.document import DocumentType, document_type_for_suffix
from bom_intelligence.profiler.common import (
    KeywordHit,
    ReadError,
    _Model,
    clip,
    detect_container_problem,
)
from bom_intelligence.vocabulary import Vocabulary, default_vocabulary

ShapeKind = Literal["text", "table", "picture", "chart", "group", "ole", "other"]
PptLayoutHint = Literal["table", "layout", "image", "no_bom_content"]

MAX_LABEL_LENGTH = 40
_INLINE_SEPARATOR = re.compile(r"[:：=＝]\s*(.+)$")


class ShapeObservation(_Model):
    slide: int
    shape_id: int
    name: str
    kind: ShapeKind
    left: int | None
    top: int | None
    width: int | None
    height: int | None
    text: str | None = None
    parent_group_id: int | None = None
    table_rows: int | None = None
    table_columns: int | None = None


class TableHeaderColumn(_Model):
    column: int
    text: str
    category: str | None
    subtype: str | None
    exact: bool


class TableHeader(_Model):
    slide: int
    shape_id: int
    rows: int
    columns: tuple[TableHeaderColumn, ...]

    def columns_for(self, category: str) -> list[TableHeaderColumn]:
        return [c for c in self.columns if c.category == category]


class LabelValuePair(_Model):
    slide: int
    category: str
    label_shape_id: int
    label_text: str
    value_shape_id: int | None
    value_text: str | None
    relation: Literal["inline", "right", "below"]
    distance_emu: int = 0


class SlideProfile(_Model):
    number: int
    shape_count: int
    shape_kinds: dict[str, int]
    picture_area_ratio: float
    text_characters: int
    shapes: tuple[ShapeObservation, ...]
    keyword_hits: tuple[KeywordHit, ...]
    table_headers: tuple[TableHeader, ...]
    label_value_pairs: tuple[LabelValuePair, ...]
    layout_hint: PptLayoutHint


class PowerPointProfile(_Model):
    kind: Literal["powerpoint"] = "powerpoint"
    file: str
    document_type: DocumentType
    read_error: ReadError | None = None
    slide_count: int = 0
    slide_width: int | None = None
    slide_height: int | None = None
    slides: tuple[SlideProfile, ...] = ()
    layout_hint: PptLayoutHint = "no_bom_content"


def _kind(shape: BaseShape) -> ShapeKind:
    try:
        shape_type = shape.shape_type
    except NotImplementedError:
        shape_type = None
    if isinstance(shape, GroupShape):
        return "group"
    if shape_type in (MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT, MSO_SHAPE_TYPE.LINKED_OLE_OBJECT):
        return "ole"
    if isinstance(shape, GraphicFrame):
        if shape.has_table:
            return "table"
        if shape.has_chart:
            return "chart"
        return "other"
    if isinstance(shape, Picture) or shape_type == MSO_SHAPE_TYPE.PICTURE:
        return "picture"
    if shape.has_text_frame:
        return "text"
    return "other"


def _walk(shapes: object, parent: int | None = None) -> Iterator[tuple[BaseShape, int | None]]:
    for shape in shapes:  # type: ignore[attr-defined]
        yield shape, parent
        if isinstance(shape, GroupShape):
            yield from _walk(shape.shapes, shape.shape_id)


def _int(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[call-overload]


def _right_or_below(
    label: ShapeObservation, others: list[ShapeObservation]
) -> tuple[ShapeObservation, Literal["right", "below"], int] | None:
    if None in (label.left, label.top, label.width, label.height):
        return None
    assert label.left is not None and label.top is not None
    assert label.width is not None and label.height is not None
    l_right, l_bottom = label.left + label.width, label.top + label.height
    best: tuple[ShapeObservation, Literal["right", "below"], int] | None = None
    for other in others:
        if other.shape_id == label.shape_id or not other.text:
            continue
        if None in (other.left, other.top, other.width, other.height):
            continue
        assert other.left is not None and other.top is not None
        assert other.width is not None and other.height is not None
        o_bottom, o_right = other.top + other.height, other.left + other.width
        v_overlap = min(l_bottom, o_bottom) - max(label.top, other.top)
        h_overlap = min(l_right, o_right) - max(label.left, other.left)
        candidate: tuple[ShapeObservation, Literal["right", "below"], int] | None = None
        if other.left >= l_right - 1 and v_overlap > 0:
            candidate = (other, "right", other.left - l_right)
        elif other.top >= l_bottom - 1 and h_overlap > 0:
            candidate = (other, "below", other.top - l_bottom)
        if candidate and (best is None or candidate[2] < best[2]):
            best = candidate
    return best


def _profile_slide(slide: object, number: int, slide_area: int, vocab: Vocabulary) -> SlideProfile:
    observations: list[ShapeObservation] = []
    hits: list[KeywordHit] = []
    headers: list[TableHeader] = []
    kinds: dict[str, int] = {}
    picture_area = 0
    text_chars = 0
    for shape, parent in _walk(slide.shapes):  # type: ignore[attr-defined]
        kind = _kind(shape)
        kinds[kind] = kinds.get(kind, 0) + 1
        text: str | None = None
        rows = cols = None
        if kind == "text" and shape.has_text_frame:
            text = shape.text_frame.text.strip() or None  # type: ignore[attr-defined]
        if kind == "table" and isinstance(shape, GraphicFrame):
            table = shape.table
            rows, cols = len(table.rows), len(table.columns)
            header_cols: list[TableHeaderColumn] = []
            for r_index, row in enumerate(table.rows):
                for c_index, cell in enumerate(row.cells):
                    cell_text = cell.text.strip()
                    if not cell_text:
                        continue
                    text_chars += len(cell_text)
                    for match in vocab.find_keywords(cell_text):
                        hits.append(
                            KeywordHit(
                                category=match.category.value,
                                alias=match.alias,
                                exact=match.exact,
                                text=clip(cell_text),
                                slide=number,
                                shape_id=shape.shape_id,
                                cell=f"R{r_index + 1}C{c_index + 1}",
                            )
                        )
                    if r_index == 0:
                        m = vocab.match_header(cell_text)
                        header_cols.append(
                            TableHeaderColumn(
                                column=c_index + 1,
                                text=clip(cell_text),
                                category=None if m is None else m.category.value,
                                subtype=None if m is None else m.subtype,
                                exact=m is not None,
                            )
                        )
            if len({c.category for c in header_cols if c.category}) >= 2:
                headers.append(
                    TableHeader(
                        slide=number, shape_id=shape.shape_id, rows=rows, columns=tuple(header_cols)
                    )
                )
        if kind == "picture" and shape.width is not None and shape.height is not None:
            picture_area += int(shape.width) * int(shape.height)
        if text:
            text_chars += len(text)
            for match in vocab.find_keywords(text):
                hits.append(
                    KeywordHit(
                        category=match.category.value,
                        alias=match.alias,
                        exact=match.exact,
                        text=clip(text),
                        slide=number,
                        shape_id=shape.shape_id,
                    )
                )
        observations.append(
            ShapeObservation(
                slide=number,
                shape_id=shape.shape_id,
                name=shape.name,
                kind=kind,
                left=_int(shape.left),
                top=_int(shape.top),
                width=_int(shape.width),
                height=_int(shape.height),
                text=None if text is None else clip(text, 500),
                parent_group_id=parent,
                table_rows=rows,
                table_columns=cols,
            )
        )

    pairs: list[LabelValuePair] = []
    text_shapes = [o for o in observations if o.kind == "text" and o.text]
    for hit in hits:
        if hit.cell is not None or hit.shape_id is None:
            continue
        label = next(o for o in text_shapes if o.shape_id == hit.shape_id)
        assert label.text is not None
        inline = None
        for line in label.text.splitlines():
            head = _INLINE_SEPARATOR.split(line, maxsplit=1)[0]
            if any(m.category.value == hit.category for m in vocab.find_keywords(head)):
                inline = _INLINE_SEPARATOR.search(line)
                if inline:
                    break
        if inline:
            pairs.append(
                LabelValuePair(
                    slide=number,
                    category=hit.category,
                    label_shape_id=label.shape_id,
                    label_text=label.text,
                    value_shape_id=label.shape_id,
                    value_text=inline.group(1).strip(),
                    relation="inline",
                )
            )
            continue
        if "\n" in label.text and _INLINE_SEPARATOR.search(label.text):
            continue  # multi-line box with inline values for other labels only
        if len(label.text) > MAX_LABEL_LENGTH:
            continue
        near = _right_or_below(label, text_shapes)
        pairs.append(
            LabelValuePair(
                slide=number,
                category=hit.category,
                label_shape_id=label.shape_id,
                label_text=label.text,
                value_shape_id=None if near is None else near[0].shape_id,
                value_text=None if near is None else near[0].text,
                relation="right" if near is None else near[1],
                distance_emu=0 if near is None else near[2],
            )
        )

    ratio = round(picture_area / slide_area, 4) if slide_area else 0.0
    hint: PptLayoutHint
    if headers:
        hint = "table"
    elif any(h.cell is None for h in hits):
        hint = "layout"
    elif kinds.get("picture", 0) and text_chars < 20:
        hint = "image"
    else:
        hint = "no_bom_content"
    return SlideProfile(
        number=number,
        shape_count=len(observations),
        shape_kinds=dict(sorted(kinds.items())),
        picture_area_ratio=ratio,
        text_characters=text_chars,
        shapes=tuple(observations),
        keyword_hits=tuple(hits),
        table_headers=tuple(headers),
        label_value_pairs=tuple(pairs),
        layout_hint=hint,
    )


def profile_powerpoint(
    path: Path, *, display_name: str | None = None, vocabulary: Vocabulary | None = None
) -> PowerPointProfile:
    """Profile a presentation. Never raises for bad input; see ``read_error``."""
    vocab = vocabulary or default_vocabulary()
    name = display_name or path.name
    doc_type = document_type_for_suffix(path.suffix)
    problem = detect_container_problem(path)
    if problem is not None:
        return PowerPointProfile(file=name, document_type=doc_type, read_error=problem)
    try:
        prs = Presentation(str(path))
    except Exception as exc:  # python-pptx raises many types for malformed packages
        return PowerPointProfile(
            file=name,
            document_type=doc_type,
            read_error=ReadError(
                code=FailureCode.UNREADABLE_FILE, message=f"{type(exc).__name__}: {exc}"
            ),
        )
    width, height = _int(prs.slide_width), _int(prs.slide_height)
    area = (width or 0) * (height or 0)
    slides = [_profile_slide(s, i + 1, area, vocab) for i, s in enumerate(prs.slides)]
    hints = {s.layout_hint for s in slides}
    overall: PptLayoutHint = "no_bom_content"
    order: tuple[PptLayoutHint, ...] = ("table", "layout", "image")
    for candidate in order:
        if candidate in hints:
            overall = candidate
            break
    return PowerPointProfile(
        file=name,
        document_type=doc_type,
        slide_count=len(slides),
        slide_width=width,
        slide_height=height,
        slides=tuple(slides),
        layout_hint=overall,
    )
