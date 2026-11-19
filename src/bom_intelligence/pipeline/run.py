"""End-to-end batch run: scan, profile, diagnose, route, extract.

One malformed document never stops the batch: unexpected exceptions are caught per
document and recorded as an ``UNKNOWN`` diagnostic with the exception text.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bom_intelligence import __version__
from bom_intelligence.analyzer.diagnose import diagnose_unsupported
from bom_intelligence.models.bom import BOMRecord
from bom_intelligence.models.diagnostics import (
    Diagnostic,
    FailureCode,
    Severity,
    SuggestedStrategy,
)
from bom_intelligence.models.document import DocumentType
from bom_intelligence.pipeline.adapters import default_registry
from bom_intelligence.pipeline.contracts import (
    AdapterRegistry,
    DocumentRef,
    RouteStrategy,
    StrategyDecision,
)
from bom_intelligence.pipeline.router import route
from bom_intelligence.profiler.common import ProfileBase
from bom_intelligence.scanner.inventory import (
    InventoryEntry,
    scan_directory,
    write_inventory_jsonl,
)

RESULTS_FILE = "results.jsonl"
RECORDS_FILE = "records.jsonl"
INVENTORY_FILE = "inventory.jsonl"
RUN_FILE = "run.json"


class DocumentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    document_type: DocumentType
    sha256: str | None
    size_bytes: int | None
    duplicate_group: str | None
    profiler: str | None
    profile_kind: str | None
    layout_hint: str | None
    profile_stats: dict[str, int | float]
    diagnostics: tuple[Diagnostic, ...]
    decision: StrategyDecision
    extractor: str | None = None
    extraction_notes: tuple[str, ...] = ()
    records: tuple[BOMRecord, ...] = ()

    @property
    def extraction_succeeded(self) -> bool:
        return bool(self.records)


def _internal_error(entry: InventoryEntry, exc: Exception) -> Diagnostic:
    return Diagnostic(
        file=entry.path,
        document_type=entry.document_type,
        code=FailureCode.UNKNOWN,
        severity=Severity.ERROR,
        message=f"internal error: {type(exc).__name__}: {exc}",
        suggested_strategy=SuggestedStrategy.HUMAN_REVIEW,
    )


def process_document(
    root: Path, entry: InventoryEntry, registry: AdapterRegistry
) -> DocumentResult:
    ref = DocumentRef(
        path=root / entry.path,
        relative_path=entry.path,
        sha256=entry.sha256,
        document_type=entry.document_type,
    )
    base = {
        "path": entry.path,
        "document_type": entry.document_type,
        "sha256": entry.sha256,
        "size_bytes": entry.size_bytes,
        "duplicate_group": entry.duplicate_group,
    }
    if entry.error is not None:
        diag = Diagnostic(
            file=entry.path,
            document_type=entry.document_type,
            code=FailureCode.UNREADABLE_FILE,
            severity=Severity.ERROR,
            message=f"{entry.error.code}: {entry.error.message}",
            suggested_strategy=SuggestedStrategy.UNSUPPORTED,
        )
        return DocumentResult(
            **base,
            profiler=None,
            profile_kind=None,
            layout_hint=None,
            profile_stats={},
            diagnostics=(diag,),
            decision=StrategyDecision(
                strategy=RouteStrategy.UNSUPPORTED,
                reasons=(FailureCode.UNREADABLE_FILE,),
                explanation="File could not be read during scan.",
            ),
        )

    profiler = registry.profiler_for(ref)
    profile: ProfileBase | None = None
    try:
        if profiler is None:
            diagnostics = diagnose_unsupported(entry.path, entry.document_type)
        else:
            profile = profiler.profile(ref)
            diagnostics = profiler.diagnose(profile)
        decision = route(entry.document_type, profile, diagnostics)
    except Exception as exc:  # keep the batch going
        diagnostics = [_internal_error(entry, exc)]
        decision = route(entry.document_type, profile, diagnostics)

    extractor_name: str | None = None
    notes: tuple[str, ...] = ()
    records: tuple[BOMRecord, ...] = ()
    extractor = registry.extractor_for(ref, decision.strategy)
    if extractor is not None and profile is not None:
        extractor_name = extractor.name
        try:
            result = extractor.extract(ref, profile)
            records, notes = result.records, result.notes
            known = set(diagnostics)
            diagnostics = list(diagnostics) + [d for d in result.diagnostics if d not in known]
        except Exception as exc:  # keep the batch going
            diagnostics = [*diagnostics, _internal_error(entry, exc)]
            notes = ("extractor crashed",)

    return DocumentResult(
        **base,
        profiler=None if profiler is None else profiler.name,
        profile_kind=None if profile is None else profile.kind,
        layout_hint=None if profile is None else profile.layout_hint,
        profile_stats={} if profile is None else profile.stats(),
        diagnostics=tuple(diagnostics),
        decision=decision,
        extractor=extractor_name,
        extraction_notes=notes,
        records=records,
    )


def analyze_directory(
    root: Path, output_dir: Path, registry: AdapterRegistry | None = None
) -> list[DocumentResult]:
    root = root.resolve()
    registry = registry or default_registry()
    entries = scan_directory(root)
    results = [process_document(root, entry, registry) for entry in entries]
    output_dir.mkdir(parents=True, exist_ok=True)
    write_inventory_jsonl(entries, output_dir / INVENTORY_FILE)
    write_results(results, output_dir)
    (output_dir / RUN_FILE).write_text(
        json.dumps({"tool_version": __version__, "documents": len(results)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return results


def write_results(results: Iterable[DocumentResult], output_dir: Path) -> None:
    with (
        (output_dir / RESULTS_FILE).open("w", encoding="utf-8", newline="\n") as res,
        (output_dir / RECORDS_FILE).open("w", encoding="utf-8", newline="\n") as rec,
    ):
        for result in results:
            res.write(result.model_dump_json() + "\n")
            for record in result.records:
                rec.write(record.model_dump_json() + "\n")


def read_results(output_dir: Path) -> list[DocumentResult]:
    with (output_dir / RESULTS_FILE).open(encoding="utf-8") as handle:
        return [DocumentResult.model_validate_json(line) for line in handle if line.strip()]
