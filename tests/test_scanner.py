from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from bom_intelligence.cli import main
from bom_intelligence.models import DocumentType
from bom_intelligence.scanner import read_inventory_jsonl, scan_directory


def _tree(root: Path) -> None:
    (root / "a" / "b").mkdir(parents=True)
    (root / "top.xlsx").write_bytes(b"same-bytes")
    (root / "a" / "copy.xlsx").write_bytes(b"same-bytes")
    (root / "a" / "b" / "deck.PPTX").write_bytes(b"deck")
    (root / "a" / "notes.txt").write_text("hello")
    (root / "a" / "b" / "scan.pdf").write_bytes(b"%PDF")


def test_recursive_scan_and_types(tmp_path: Path) -> None:
    _tree(tmp_path)
    entries = scan_directory(tmp_path)
    paths = [e.path for e in entries]
    assert paths == sorted(paths)
    assert paths == ["a/b/deck.PPTX", "a/b/scan.pdf", "a/copy.xlsx", "a/notes.txt", "top.xlsx"]
    by_path = {e.path: e for e in entries}
    assert by_path["a/b/deck.PPTX"].document_type is DocumentType.PPTX
    assert by_path["a/notes.txt"].document_type is DocumentType.OTHER
    assert not by_path["a/notes.txt"].supported
    assert not by_path["a/b/scan.pdf"].supported
    assert by_path["top.xlsx"].supported
    assert by_path["top.xlsx"].sha256 is not None
    assert by_path["top.xlsx"].size_bytes == len(b"same-bytes")


def test_duplicates_grouped(tmp_path: Path) -> None:
    _tree(tmp_path)
    entries = {e.path: e for e in scan_directory(tmp_path)}
    group = entries["top.xlsx"].duplicate_group
    assert group is not None
    assert entries["a/copy.xlsx"].duplicate_group == group
    assert entries["a/notes.txt"].duplicate_group is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_unreadable_file_recorded(tmp_path: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        target = tmp_path / "broken.xlsx"
        target.symlink_to(tmp_path / "missing.xlsx")
        expected = "NOT_FOUND"
    else:
        target = tmp_path / "locked.xlsx"
        target.write_bytes(b"x")
        target.chmod(0)
        expected = "PERMISSION_DENIED"
    (tmp_path / "ok.xlsx").write_bytes(b"ok")
    entries = {e.filename: e for e in scan_directory(tmp_path)}
    bad = entries[target.name]
    assert bad.error is not None and bad.error.code == expected
    assert bad.sha256 is None
    assert not bad.supported
    assert entries["ok.xlsx"].error is None


def test_scanner_does_not_modify_files(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    scan_directory(tmp_path)
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_cli_scan_jsonl_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    _tree(root)
    out1, out2 = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    csv_path = tmp_path / "inv.csv"
    assert main(["scan", str(root), "--output", str(out1), "--csv", str(csv_path)]) == 0
    assert main(["scan", str(root), "--output", str(out2)]) == 0
    assert out1.read_bytes() == out2.read_bytes()
    lines = out1.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert all(json.loads(line)["path"] for line in lines)
    assert len(read_inventory_jsonl(out1)) == 5
    assert csv_path.read_text(encoding="utf-8-sig").startswith("path,filename")
