"""Regression tests for review findings on the Phase 1 PR."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from bom_intelligence.analyzer import diagnose_excel, diagnose_powerpoint
from bom_intelligence.models import FailureCode
from bom_intelligence.profiler import profile_excel, profile_powerpoint
from bom_intelligence.scanner import scan_directory


def test_header_detection_is_not_quadratic(tmp_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Part No", "Part Name", "Unit Price", "SOP", "A", "B", "C", "D"])
    for i in range(4000):
        ws.append([f"P-{i}", "x", i, "2027-01-01", 1, 2, 3, 4])
    path = tmp_path / "big.xlsx"
    wb.save(path)
    start = time.perf_counter()
    profile = profile_excel(path)
    assert time.perf_counter() - start < 20
    assert profile.sheets[0].table_regions[0].data_rows == 4000


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="needs non-root")
def test_unlistable_directory_is_reported(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "a.xlsx").write_bytes(b"x")
    locked.chmod(0)
    try:
        entries = scan_directory(tmp_path)
    finally:
        locked.chmod(0o755)
    bad = [e for e in entries if e.error and e.error.code == "DIRECTORY_UNREADABLE"]
    assert [e.path for e in bad] == ["locked/"]


def test_walk_errors_are_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_walk = os.walk

    def fake_walk(top: str | Path, **kwargs: object):  # type: ignore[no-untyped-def]
        onerror = kwargs.get("onerror")
        assert callable(onerror)
        onerror(PermissionError(13, "Permission denied", str(Path(top) / "secret")))
        yield from real_walk(top, followlinks=False)

    monkeypatch.setattr(os, "walk", fake_walk)
    (tmp_path / "ok.xlsx").write_bytes(b"x")
    entries = scan_directory(tmp_path)
    assert [e.path for e in entries] == ["ok.xlsx", "secret/"]
    assert entries[1].error is not None and entries[1].error.code == "DIRECTORY_UNREADABLE"


def test_formula_in_table_detected_beyond_sample_cap(tmp_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for r in range(1, 601):
        ws.cell(row=r, column=1, value=f"=ROW()*{r}")
    ws["C700"], ws["D700"] = "Part No", "Unit Price"
    ws["C701"], ws["D701"] = "P-1", "=10*2"
    path = tmp_path / "formulas.xlsx"
    wb.save(path)
    codes = {d.code for d in diagnose_excel(profile_excel(path))}
    assert FailureCode.FORMULA_DEPENDENCY in codes


def _deck(tmp_path: Path, build) -> Path:  # type: ignore[no-untyped-def]
    prs = Presentation()
    build(prs)
    path = tmp_path / "deck.pptx"
    prs.save(str(path))
    return path


def test_freeform_slide_diagnosed_even_if_other_slide_has_table(tmp_path: Path) -> None:
    def build(prs) -> None:  # type: ignore[no-untyped-def]
        s1 = prs.slides.add_slide(prs.slide_layouts[6])
        t = s1.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(1)).table
        t.cell(0, 0).text, t.cell(0, 1).text = "品番", "単価"
        t.cell(1, 0).text, t.cell(1, 1).text = "P-1", "10"
        s2 = prs.slides.add_slide(prs.slide_layouts[6])
        s2.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text_frame.text = "品番"
        s2.shapes.add_textbox(Inches(4), Inches(1), Inches(2), Inches(1)).text_frame.text = "P-2"

    diags = diagnose_powerpoint(profile_powerpoint(_deck(tmp_path, build)))
    freeform = [d for d in diags if d.code is FailureCode.FREEFORM_LAYOUT]
    assert freeform and all(o.location.slide == 2 for o in freeform[0].evidence)


def test_table_keywords_without_header_reported(tmp_path: Path) -> None:
    def build(prs) -> None:  # type: ignore[no-untyped-def]
        s = prs.slides.add_slide(prs.slide_layouts[6])
        t = s.shapes.add_table(3, 2, Inches(1), Inches(1), Inches(4), Inches(1)).table
        t.cell(0, 0).text = "Parts list Q3"
        t.cell(1, 0).text, t.cell(1, 1).text = "品番", "単価"
        t.cell(2, 0).text, t.cell(2, 1).text = "P-1", "10"

    codes = {d.code for d in diagnose_powerpoint(profile_powerpoint(_deck(tmp_path, build)))}
    assert FailureCode.HEADER_NOT_FOUND in codes


def test_inline_values_matched_to_their_own_label(tmp_path: Path) -> None:
    def build(prs) -> None:  # type: ignore[no-untyped-def]
        s = prs.slides.add_slide(prs.slide_layouts[6])
        box = s.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1))
        box.text_frame.text = "Part No: SYN-1\nCost: $10"

    slide = profile_powerpoint(_deck(tmp_path, build)).slides[0]
    pairs = {(p.category, p.value_text) for p in slide.label_value_pairs}
    assert pairs == {("part_number", "SYN-1"), ("cost", "$10")}
