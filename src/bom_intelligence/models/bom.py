"""Canonical, format-independent BOM output contract.

Every parser or AI adapter must produce these models. Office-specific details live
only under :class:`SourceReference`; the business fields stay format-agnostic.

Design rules:

* Original text is always preserved next to any normalized value.
* Ambiguous values are left un-normalized (``None``) with a warning instead of
  being coerced.
* Every business value can carry its own exact source location.
* JSON serialization is deterministic (fixed field order, no sets).
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from bom_intelligence.models.document import DocumentType

SCHEMA_VERSION = "1.0"

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

_TABLE_CELL = re.compile(r"^R[1-9][0-9]*C[1-9][0-9]*$")
_CELL_RANGE = re.compile(r"^\$?[A-Z]{1,3}\$?[1-9][0-9]*(:\$?[A-Z]{1,3}\$?[1-9][0-9]*)?$")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class ExtractionMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"
    OCR = "ocr"
    HUMAN = "human"


class CostType(StrEnum):
    PROTOTYPE = "prototype"
    PRODUCTION = "production"
    ESTIMATE = "estimate"
    UNKNOWN = "unknown"


class MilestoneType(StrEnum):
    SOP = "sop"
    PROTOTYPE = "prototype"
    DELIVERY = "delivery"
    DRAWING = "drawing"
    UNKNOWN = "unknown"


class SourceReference(_Model):
    """Exact location of a value inside a source document."""

    filename: NonEmptyStr
    file_sha256: Sha256
    document_type: DocumentType
    sheet: str | None = None
    slide: Annotated[int, Field(ge=1)] | None = None
    page: Annotated[int, Field(ge=1)] | None = None
    cell_range: str | None = Field(default=None, description="A1-style cell or range")
    shape_id: int | None = None
    table_cell: str | None = Field(
        default=None, description="R<row>C<col> cell inside a slide/page table (1-based)"
    )
    original_text: str | None = None

    @model_validator(mode="after")
    def _check_location(self) -> Self:
        if self.cell_range is not None and not _CELL_RANGE.match(self.cell_range):
            raise ValueError(f"invalid A1 cell range: {self.cell_range!r}")
        if self.cell_range is not None and self.sheet is None:
            raise ValueError("cell_range requires sheet")
        if self.shape_id is not None and self.slide is None and self.page is None:
            raise ValueError("shape_id requires slide or page")
        if self.table_cell is not None:
            if not _TABLE_CELL.match(self.table_cell):
                raise ValueError(f"invalid table cell: {self.table_cell!r}")
            if self.shape_id is None:
                raise ValueError("table_cell requires shape_id")
        return self


class ExtractionEvidence(_Model):
    """A piece of evidence used to produce a value (e.g. a header cell)."""

    field: NonEmptyStr
    source: SourceReference
    note: str | None = None


class PartIdentity(_Model):
    part_number: NonEmptyStr
    part_name: str | None = None
    supplier: str | None = None
    category: str | None = None
    source: SourceReference | None = None


class CostInfo(_Model):
    """A cost value. ``value`` is ``None`` when the original text is ambiguous."""

    value: Decimal | None = None
    original_text: str
    currency: CurrencyCode | None = None
    cost_type: CostType = CostType.UNKNOWN
    unit_basis: str | None = None
    source: SourceReference | None = None

    @model_validator(mode="after")
    def _check_value(self) -> Self:
        if self.value is not None and not self.value.is_finite():
            raise ValueError("cost value must be finite")
        return self


class ScheduleInfo(_Model):
    """A schedule value: a single date, a date range, or only original text."""

    date: dt.date | None = None
    range_start: dt.date | None = None
    range_end: dt.date | None = None
    original_text: str
    milestone_type: MilestoneType = MilestoneType.UNKNOWN
    source: SourceReference | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> Self:
        has_range = self.range_start is not None or self.range_end is not None
        if self.date is not None and has_range:
            raise ValueError("use either date or range_start/range_end, not both")
        if (self.range_start is None) != (self.range_end is None):
            raise ValueError("range_start and range_end must be given together")
        if (
            self.range_start is not None
            and self.range_end is not None
            and self.range_start > self.range_end
        ):
            raise ValueError("range_start must not be after range_end")
        return self


class ExtractionMetadata(_Model):
    method: ExtractionMethod
    confidence: Confidence
    parser_version: NonEmptyStr
    warnings: tuple[str, ...] = ()
    evidence: tuple[ExtractionEvidence, ...] = ()


class BOMRecord(_Model):
    """One canonical BOM line item."""

    schema_version: str = SCHEMA_VERSION
    part: PartIdentity
    costs: tuple[CostInfo, ...] = ()
    schedules: tuple[ScheduleInfo, ...] = ()
    metadata: ExtractionMetadata

    def to_json(self) -> str:
        """Deterministic JSON (stable field order, no extra whitespace variance)."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str | bytes) -> BOMRecord:
        return cls.model_validate_json(data)
