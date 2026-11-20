from __future__ import annotations

from pathlib import Path

from bom_intelligence.models import FailureCode
from bom_intelligence.profiler import profile_excel, profile_powerpoint


def test_excel_clean_table(fixture_dir: Path) -> None:
    p = profile_excel(fixture_dir / "excel/clean_table.xlsx")
    assert p.read_error is None
    assert p.sheet_count == 1
    assert p.layout_hint == "regular_table"
    sheet = p.sheets[0]
    assert sheet.name == "BOM"
    assert sheet.non_empty_cells == 16
    (header,) = sheet.header_candidates
    assert header.range == "A1:D1"
    assert header.categories() == ["part_number", "part_name", "cost", "schedule"]
    assert [c.cell for c in header.columns] == ["A1", "B1", "C1", "D1"]
    assert sheet.table_regions[0].range == "A1:D4"
    assert sheet.table_regions[0].data_rows == 3


def test_excel_shifted_header(fixture_dir: Path) -> None:
    sheet = profile_excel(fixture_dir / "excel/shifted_header.xlsx").sheets[0]
    (header,) = sheet.header_candidates
    assert header.range == "C5:F5"
    assert sheet.table_regions[0].range == "C5:F8"


def test_excel_merged_header(fixture_dir: Path) -> None:
    p = profile_excel(fixture_dir / "excel/merged_header.xlsx")
    sheet = p.sheets[0]
    assert sheet.merged_ranges == ("A1:A2", "B1:B2", "C1:D1")
    assert sheet.header_candidates[0].range == "A1:D1"
    assert p.layout_hint == "layout"


def test_excel_multiple_tables(fixture_dir: Path) -> None:
    p = profile_excel(fixture_dir / "excel/multiple_tables.xlsx")
    assert p.layout_hint == "multi_table"
    assert [r.range for r in p.sheets[0].table_regions] == ["A1:C4", "E1:G3"]


def test_excel_hidden_content_and_formulas(fixture_dir: Path) -> None:
    hidden = profile_excel(fixture_dir / "excel/hidden_content.xlsx")
    assert hidden.sheet_count == 2
    assert [s.state for s in hidden.sheets] == ["visible", "hidden"]
    assert hidden.sheets[0].hidden_columns == ("B",)
    assert len(hidden.visible_sheets()) == 1
    formulas = profile_excel(fixture_dir / "excel/formula_values.xlsx").sheets[0]
    assert formulas.formula_cells == 3
    assert formulas.formula_samples == ("D2", "D3", "D4")


def test_excel_keyword_hits_have_coordinates(fixture_dir: Path) -> None:
    sheet = profile_excel(fixture_dir / "excel/no_header.xlsx").sheets[0]
    assert not sheet.header_candidates
    assert {(h.category, h.cell) for h in sheet.keyword_hits} >= {("part_number", "B2")}


def test_excel_bad_files_do_not_raise(fixture_dir: Path) -> None:
    protected = profile_excel(fixture_dir / "excel/password_protected.xlsx")
    assert protected.read_error is not None
    assert protected.read_error.code is FailureCode.PASSWORD_PROTECTED
    corrupt = profile_excel(fixture_dir / "excel/corrupt.xlsx")
    assert corrupt.read_error is not None
    assert corrupt.read_error.code is FailureCode.UNREADABLE_FILE


def test_ppt_native_table(fixture_dir: Path) -> None:
    p = profile_powerpoint(fixture_dir / "powerpoint/native_table.pptx")
    assert p.layout_hint == "table"
    slide = p.slides[0]
    (header,) = slide.table_headers
    assert header.rows == 4
    assert [c.category for c in header.columns] == ["part_number", "part_name", "cost", "schedule"]
    assert all(h.slide == 1 and h.shape_id == header.shape_id for h in slide.keyword_hits)


def test_ppt_freeform_text_pairs(fixture_dir: Path) -> None:
    p = profile_powerpoint(fixture_dir / "powerpoint/freeform_text.pptx")
    assert p.layout_hint == "layout"
    slide = p.slides[0]
    assert all(s.left is not None and s.width is not None for s in slide.shapes)
    pairs = {(x.category, x.value_text, x.relation) for x in slide.label_value_pairs}
    assert ("part_number", "SYN-3001", "right") in pairs
    assert ("cost", "¥980", "right") in pairs
    assert ("schedule", "2027/06/30", "inline") in pairs


def test_ppt_grouped_shapes(fixture_dir: Path) -> None:
    slide = profile_powerpoint(fixture_dir / "powerpoint/grouped_shapes.pptx").slides[0]
    assert slide.shape_kinds == {"group": 1, "text": 4}
    group_id = next(s.shape_id for s in slide.shapes if s.kind == "group")
    assert all(s.parent_group_id == group_id for s in slide.shapes if s.kind == "text")
    assert {x.value_text for x in slide.label_value_pairs} == {"SYN-5001", "$15.20"}


def test_ppt_image_heavy_and_embedded(fixture_dir: Path) -> None:
    image = profile_powerpoint(fixture_dir / "powerpoint/image_heavy.pptx")
    assert image.layout_hint == "image"
    assert image.slides[0].picture_area_ratio == 1.0
    embedded = profile_powerpoint(fixture_dir / "powerpoint/embedded_object.pptx").slides[0]
    assert embedded.shape_kinds["ole"] == 1
    assert embedded.shape_kinds["chart"] == 1


def test_ppt_bad_file_does_not_raise(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pptx"
    bad.write_bytes(b"nope")
    p = profile_powerpoint(bad)
    assert p.read_error is not None
    assert p.read_error.code is FailureCode.UNREADABLE_FILE
