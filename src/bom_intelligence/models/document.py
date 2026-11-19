"""Format-level document identifiers shared by the scanner, profilers, and schema."""

from __future__ import annotations

from enum import StrEnum


class DocumentType(StrEnum):
    """Detected document type. Values are stable machine-readable codes."""

    XLSX = "xlsx"
    XLSM = "xlsm"
    XLS = "xls"
    PPTX = "pptx"
    PPT = "ppt"
    PDF = "pdf"
    IMAGE = "image"
    OTHER = "other"


EXTENSION_TO_TYPE: dict[str, DocumentType] = {
    ".xlsx": DocumentType.XLSX,
    ".xlsm": DocumentType.XLSM,
    ".xls": DocumentType.XLS,
    ".pptx": DocumentType.PPTX,
    ".ppt": DocumentType.PPT,
    ".pdf": DocumentType.PDF,
    ".png": DocumentType.IMAGE,
    ".jpg": DocumentType.IMAGE,
    ".jpeg": DocumentType.IMAGE,
    ".gif": DocumentType.IMAGE,
    ".bmp": DocumentType.IMAGE,
    ".tif": DocumentType.IMAGE,
    ".tiff": DocumentType.IMAGE,
    ".webp": DocumentType.IMAGE,
}


def document_type_for_suffix(suffix: str) -> DocumentType:
    """Map a file suffix (with or without the dot, any case) to a document type."""
    normalized = suffix.lower()
    if normalized and not normalized.startswith("."):
        normalized = "." + normalized
    return EXTENSION_TO_TYPE.get(normalized, DocumentType.OTHER)
