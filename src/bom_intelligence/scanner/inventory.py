"""Inventory candidate files without interpreting their business meaning.

The scanner only reads bytes (for hashing) and file metadata. It never modifies,
opens with Office, or executes anything in the scanned files.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import os
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bom_intelligence.models.document import DocumentType, document_type_for_suffix

SUPPORTED_TYPES: frozenset[DocumentType] = frozenset(
    {DocumentType.XLSX, DocumentType.XLSM, DocumentType.PPTX}
)
"""Types with a profiler today. Others are inventoried but marked unsupported."""

_CHUNK = 1024 * 1024


class ScanError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str


class InventoryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    """POSIX path relative to the scan root."""
    filename: str
    extension: str
    document_type: DocumentType
    size_bytes: int | None
    modified_time: str | None
    """UTC ISO-8601 modification time."""
    sha256: str | None
    duplicate_group: str | None = None
    supported: bool
    error: ScanError | None = None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path, errors: list[OSError]) -> Iterable[Path]:
    # Do not follow directory symlinks: avoids cycles and escaping the scan root.
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=errors.append):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _scan_one(root: Path, path: Path) -> InventoryEntry:
    rel = path.relative_to(root).as_posix()
    suffix = path.suffix.lower()
    doc_type = document_type_for_suffix(suffix)
    size: int | None = None
    mtime: str | None = None
    sha: str | None = None
    error: ScanError | None = None
    try:
        stat = path.stat()
        size = stat.st_size
        mtime = (
            dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.UTC).replace(microsecond=0).isoformat()
        )
        sha = _hash_file(path)
    except PermissionError as exc:
        error = ScanError(code="PERMISSION_DENIED", message=str(exc))
    except FileNotFoundError as exc:
        error = ScanError(code="NOT_FOUND", message=f"broken link or removed: {exc}")
    except OSError as exc:
        error = ScanError(code="READ_ERROR", message=str(exc))
    return InventoryEntry(
        path=rel,
        filename=path.name,
        extension=suffix,
        document_type=doc_type,
        size_bytes=size,
        modified_time=mtime,
        sha256=sha,
        supported=doc_type in SUPPORTED_TYPES and error is None,
        error=error,
    )


def scan_directory(root: Path) -> list[InventoryEntry]:
    """Recursively inventory ``root``. Results are sorted by relative path."""
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    walk_errors: list[OSError] = []
    entries = [_scan_one(root, path) for path in _iter_files(root, walk_errors)]
    for err in walk_errors:
        target = Path(err.filename) if err.filename else root
        try:
            rel = target.relative_to(root).as_posix() or "."
        except ValueError:
            rel = str(target)
        entries.append(
            InventoryEntry(
                path=rel if rel.endswith("/") else rel + "/",
                filename=target.name,
                extension="",
                document_type=DocumentType.OTHER,
                size_bytes=None,
                modified_time=None,
                sha256=None,
                supported=False,
                error=ScanError(
                    code="DIRECTORY_UNREADABLE",
                    message=f"directory could not be listed; its files are missing: {err}",
                ),
            )
        )
    entries.sort(key=lambda e: e.path)

    by_hash: dict[str, list[int]] = defaultdict(list)
    for index, entry in enumerate(entries):
        if entry.sha256 is not None:
            by_hash[entry.sha256].append(index)
    for sha, indexes in by_hash.items():
        if len(indexes) > 1:
            group = f"dup-{sha[:12]}"
            for index in indexes:
                entries[index] = entries[index].model_copy(update={"duplicate_group": group})
    return entries


def write_inventory_jsonl(entries: Iterable[InventoryEntry], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(entry.model_dump_json())
            handle.write("\n")


def read_inventory_jsonl(path: Path) -> list[InventoryEntry]:
    with path.open(encoding="utf-8") as handle:
        return [InventoryEntry.model_validate_json(line) for line in handle if line.strip()]


CSV_COLUMNS = (
    "path",
    "filename",
    "extension",
    "document_type",
    "size_bytes",
    "modified_time",
    "sha256",
    "duplicate_group",
    "supported",
    "error_code",
    "error_message",
)


def write_inventory_csv(entries: Iterable[InventoryEntry], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for e in entries:
            writer.writerow(
                [
                    e.path,
                    e.filename,
                    e.extension,
                    e.document_type.value,
                    "" if e.size_bytes is None else e.size_bytes,
                    e.modified_time or "",
                    e.sha256 or "",
                    e.duplicate_group or "",
                    str(e.supported).lower(),
                    e.error.code if e.error else "",
                    e.error.message if e.error else "",
                ]
            )
