"""Shared profiler types."""

from __future__ import annotations

import zipfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bom_intelligence.models.diagnostics import FailureCode
from bom_intelligence.models.document import DocumentType

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReadError(_Model):
    """Why a document could not be profiled at all."""

    code: FailureCode
    message: str


class ProfileBase(_Model):
    """Fields every document profile shares, whatever its format."""

    kind: str
    file: str
    document_type: DocumentType
    read_error: ReadError | None = None
    layout_hint: str = "no_bom_content"

    def stats(self) -> dict[str, int | float]:
        """Small numeric summary kept in pipeline results."""
        return {}


class KeywordHit(_Model):
    category: str
    alias: str
    exact: bool
    text: str
    sheet: str | None = None
    cell: str | None = None
    slide: int | None = None
    shape_id: int | None = None


def detect_container_problem(path: Path) -> ReadError | None:
    """Classify OOXML container problems without parsing content.

    An OOXML file (xlsx/xlsm/pptx) that is an OLE compound file instead of a ZIP is
    an encrypted (password-protected) package.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError as exc:
        return ReadError(code=FailureCode.UNREADABLE_FILE, message=str(exc))
    if head == OLE_MAGIC:
        return ReadError(
            code=FailureCode.PASSWORD_PROTECTED,
            message="OOXML file is an encrypted OLE container (password protected)",
        )
    if not zipfile.is_zipfile(path):
        return ReadError(
            code=FailureCode.UNREADABLE_FILE, message="not a valid OOXML (ZIP) package"
        )
    return None


def zip_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def clip(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def range_bounds(a1: str) -> tuple[int, int, int, int]:
    """(min_col, min_row, max_col, max_row) for an A1 cell or range."""
    from openpyxl.utils import range_boundaries

    b = range_boundaries(a1)
    min_col, min_row = int(b[0] or 1), int(b[1] or 1)
    max_col, max_row = int(b[2] or min_col), int(b[3] or min_row)
    return min_col, min_row, max_col, max_row


def ranges_intersect(a: str, b: str) -> bool:
    a0, a1, a2, a3 = range_bounds(a)
    b0, b1, b2, b3 = range_bounds(b)
    return a0 <= b2 and b0 <= a2 and a1 <= b3 and b1 <= a3
