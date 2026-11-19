"""Turn a located header + rows grid into canonical records (format-neutral)."""

from __future__ import annotations

from dataclasses import dataclass, field

from bom_intelligence.extractor.normalize import parse_cost, parse_schedule
from bom_intelligence.models.bom import (
    BOMRecord,
    CostInfo,
    CostType,
    ExtractionEvidence,
    ExtractionMetadata,
    ExtractionMethod,
    MilestoneType,
    PartIdentity,
    ScheduleInfo,
    SourceReference,
)

BASE_CONFIDENCE = 0.95
WARNING_PENALTY = 0.1
MIN_CONFIDENCE = 0.5


@dataclass(frozen=True)
class GridCell:
    raw: object
    source: SourceReference

    @property
    def text(self) -> str | None:
        if self.raw is None:
            return None
        text = str(self.raw).strip()
        return text or None


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    category: str
    subtype: str | None
    header: GridCell


@dataclass
class GridRow:
    cells: dict[str, GridCell]
    warnings: list[str] = field(default_factory=list)


def _cost_type(value: str | None) -> CostType:
    try:
        return CostType(value or "unknown")
    except ValueError:
        return CostType.UNKNOWN


def _milestone(value: str | None) -> MilestoneType:
    try:
        return MilestoneType(value or "unknown")
    except ValueError:
        return MilestoneType.UNKNOWN


def build_records(
    columns: list[ColumnSpec],
    rows: list[GridRow],
    *,
    parser_version: str,
    file_warnings: list[str],
) -> tuple[list[BOMRecord], list[str]]:
    """Build one record per row that has a part number.

    Callers must already have rejected ambiguous layouts (several part/cost/schedule
    columns); this function assumes at most one column per category.
    """
    by_cat = {c.category: c for c in columns}
    part_col = by_cat["part_number"]
    evidence = tuple(
        ExtractionEvidence(field=c.category, source=c.header.source, note="header alias match")
        for c in columns
    )
    records: list[BOMRecord] = []
    skipped: list[str] = []
    for row in rows:
        part_cell = row.cells.get(part_col.key)
        if part_cell is None or part_cell.text is None:
            if any(c.text for c in row.cells.values()):
                first = next(iter(row.cells.values())).source
                skipped.append(f"row without part number skipped near {first.cell_range or ''}")
            continue
        warnings = list(row.warnings)

        def text_of(category: str, cells: dict[str, GridCell] = row.cells) -> GridCell | None:
            col = by_cat.get(category)
            return None if col is None else cells.get(col.key)

        name_cell, supplier_cell = text_of("part_name"), text_of("supplier")
        part = PartIdentity(
            part_number=part_cell.text,
            part_name=None if name_cell is None else name_cell.text,
            supplier=None if supplier_cell is None else supplier_cell.text,
            source=part_cell.source,
        )
        costs: list[CostInfo] = []
        cost_cell = text_of("cost")
        if cost_cell is not None and cost_cell.text is not None:
            col = by_cat["cost"]
            value, currency, cost_warnings = parse_cost(cost_cell.raw, col.header.text or "")
            warnings += cost_warnings
            costs.append(
                CostInfo(
                    value=value,
                    original_text=cost_cell.text,
                    currency=currency,
                    cost_type=_cost_type(col.subtype),
                    source=cost_cell.source,
                )
            )
        schedules: list[ScheduleInfo] = []
        sched_cell = text_of("schedule")
        if sched_cell is not None and sched_cell.text is not None:
            col = by_cat["schedule"]
            date, rng, sched_warnings = parse_schedule(sched_cell.raw)
            warnings += sched_warnings
            schedules.append(
                ScheduleInfo(
                    date=date,
                    range_start=None if rng is None else rng[0],
                    range_end=None if rng is None else rng[1],
                    original_text=sched_cell.text,
                    milestone_type=_milestone(col.subtype),
                    source=sched_cell.source,
                )
            )
        confidence = max(MIN_CONFIDENCE, BASE_CONFIDENCE - WARNING_PENALTY * len(warnings))
        records.append(
            BOMRecord(
                part=part,
                costs=tuple(costs),
                schedules=tuple(schedules),
                metadata=ExtractionMetadata(
                    method=ExtractionMethod.DETERMINISTIC,
                    confidence=round(confidence, 2),
                    parser_version=parser_version,
                    warnings=tuple(file_warnings + warnings),
                    evidence=evidence,
                ),
            )
        )
    return records, skipped
