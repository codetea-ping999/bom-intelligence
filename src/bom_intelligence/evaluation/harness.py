"""Compare pipeline results against version-controlled gold expectations.

Gold files are JSON, one per fixture, mirroring the fixture path
(``excel/clean_table.xlsx`` -> ``<gold>/excel/clean_table.xlsx.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bom_intelligence.models.bom import BOMRecord, SourceReference
from bom_intelligence.pipeline.run import DocumentResult

RECORD_FIELDS = (
    "part_name",
    "supplier",
    "cost_value",
    "currency",
    "cost_type",
    "schedule_date",
    "schedule_range",
    "milestone_type",
)
PROVENANCE_FIELDS = ("part_number", "cost", "schedule")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldRecord(_Model):
    part_number: str
    part_name: str | None = None
    supplier: str | None = None
    cost_value: str | None = None
    currency: str | None = None
    cost_type: str | None = None
    schedule_date: str | None = None
    schedule_range: tuple[str, str] | None = None
    milestone_type: str | None = None
    provenance: dict[str, str] = {}


class GoldDocument(_Model):
    path: str
    expected_strategy: str
    expected_codes: tuple[str, ...] = ()
    layout_hint: str | None = None
    records: tuple[GoldRecord, ...] = ()


def location_label(source: SourceReference | None) -> str | None:
    """Compact location string used by gold files: ``Sheet!A1`` or ``s1#5@R2C1``."""
    if source is None:
        return None
    if source.sheet is not None:
        return f"{source.sheet}!{source.cell_range}" if source.cell_range else source.sheet
    label = f"s{source.slide}" if source.slide is not None else f"p{source.page}"
    if source.shape_id is not None:
        label += f"#{source.shape_id}"
    if source.table_cell is not None:
        label += f"@{source.table_cell}"
    return label


def record_to_gold(record: BOMRecord) -> GoldRecord:
    cost = record.costs[0] if record.costs else None
    sched = record.schedules[0] if record.schedules else None
    provenance = {
        "part_number": location_label(record.part.source),
        "cost": None if cost is None else location_label(cost.source),
        "schedule": None if sched is None else location_label(sched.source),
    }
    rng = None
    if sched is not None and sched.range_start is not None and sched.range_end is not None:
        rng = (sched.range_start.isoformat(), sched.range_end.isoformat())
    return GoldRecord(
        part_number=record.part.part_number,
        part_name=record.part.part_name,
        supplier=record.part.supplier,
        cost_value=None
        if cost is None or cost.value is None
        else format(cost.value.normalize(), "f"),
        currency=None if cost is None else cost.currency,
        cost_type=None if cost is None else cost.cost_type.value,
        schedule_date=None if sched is None or sched.date is None else sched.date.isoformat(),
        schedule_range=rng,
        milestone_type=None if sched is None else sched.milestone_type.value,
        provenance={k: v for k, v in provenance.items() if v is not None},
    )


def result_to_gold(result: DocumentResult) -> GoldDocument:
    return GoldDocument(
        path=result.path,
        expected_strategy=result.decision.strategy.value,
        expected_codes=tuple(sorted({d.code.value for d in result.diagnostics})),
        layout_hint=result.layout_hint,
        records=tuple(record_to_gold(r) for r in result.records),
    )


def load_gold(gold_dir: Path) -> list[GoldDocument]:
    docs = [
        GoldDocument.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(gold_dir.rglob("*.json"))
    ]
    return sorted(docs, key=lambda d: d.path)


def write_gold(results: list[DocumentResult], gold_dir: Path) -> None:
    for result in results:
        target = gold_dir / f"{result.path}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = result_to_gold(result).model_dump(mode="json")
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def evaluate(results: list[DocumentResult], gold: list[GoldDocument]) -> dict[str, object]:
    """Return machine-readable metrics (deterministic key order)."""
    by_path = {r.path: r for r in results}
    docs_ok = strategy_ok = codes_ok = layout_ok = layout_total = 0
    expected_records = predicted_records = matched_records = 0
    field_total = field_ok = prov_total = prov_ok = 0
    per_field: dict[str, list[int]] = {f: [0, 0] for f in RECORD_FIELDS}
    details: list[dict[str, object]] = []
    for doc in gold:
        result = by_path.get(doc.path)
        if result is None:
            details.append({"path": doc.path, "missing": True})
            expected_records += len(doc.records)
            continue
        predicted = [record_to_gold(r) for r in result.records]
        predicted_codes = tuple(sorted({d.code.value for d in result.diagnostics}))
        s_ok = result.decision.strategy.value == doc.expected_strategy
        c_ok = predicted_codes == tuple(sorted(doc.expected_codes))
        strategy_ok += s_ok
        codes_ok += c_ok
        if doc.layout_hint is not None:
            layout_total += 1
            layout_ok += result.layout_hint == doc.layout_hint
        expected_records += len(doc.records)
        predicted_records += len(predicted)
        pred_by_pn: dict[str, list[GoldRecord]] = {}
        for item in predicted:
            pred_by_pn.setdefault(item.part_number, []).append(item)
        doc_records_exact = len(predicted) == len(doc.records)
        for g in doc.records:
            candidates = pred_by_pn.get(g.part_number, [])
            # Prefer an exact match among same-part-number predictions, else the first.
            p: GoldRecord | None = next((c for c in candidates if c == g), None) or (
                candidates[0] if candidates else None
            )
            if p is not None:
                candidates.remove(p)
            if p is None:
                doc_records_exact = False
                continue
            matched_records += 1
            for name in RECORD_FIELDS:
                same = getattr(p, name) == getattr(g, name)
                per_field[name][0] += same
                per_field[name][1] += 1
                field_ok += same
                field_total += 1
                doc_records_exact &= same
            for name in PROVENANCE_FIELDS:
                if name in g.provenance:
                    same = p.provenance.get(name) == g.provenance[name]
                    prov_ok += same
                    prov_total += 1
                    doc_records_exact &= same
        success = s_ok and c_ok and doc_records_exact
        docs_ok += success
        details.append(
            {
                "path": doc.path,
                "success": success,
                "strategy": result.decision.strategy.value,
                "expected_strategy": doc.expected_strategy,
                "codes": list(predicted_codes),
                "expected_codes": sorted(doc.expected_codes),
                "records": len(predicted),
                "expected_records": len(doc.records),
            }
        )
    false_positives = predicted_records - matched_records
    return {
        "documents": len(gold),
        "document_success_rate": _ratio(docs_ok, len(gold)),
        "strategy_accuracy": _ratio(strategy_ok, len(gold)),
        "failure_class_accuracy": _ratio(codes_ok, len(gold)),
        "layout_hint_accuracy": _ratio(layout_ok, layout_total),
        "records_expected": expected_records,
        "records_predicted": predicted_records,
        "records_matched": matched_records,
        "record_precision": _ratio(matched_records, predicted_records),
        "record_recall": _ratio(matched_records, expected_records),
        "false_positive_rate": _ratio(false_positives, predicted_records),
        "field_exact_match": _ratio(field_ok, field_total),
        "field_exact_match_by_field": {
            name: _ratio(ok, total) for name, (ok, total) in per_field.items()
        },
        "provenance_accuracy": _ratio(prov_ok, prov_total),
        "details": details,
    }
