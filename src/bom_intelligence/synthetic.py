"""Synthetic fixture documents.

Every value here is invented. These builders generate the representative Excel and
PowerPoint patterns used by tests and by the evaluation harness, so no binary
document (and no real data) needs to be committed.
"""

from __future__ import annotations

import datetime as dt
import io
import struct
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Emu, Inches, Pt

from bom_intelligence.profiler.common import OLE_MAGIC

CellValue = str | float | int | dt.date | None

CLEAN_ROWS: list[tuple[str, str, float, dt.date]] = [
    ("SYN-1001", "Bracket, front", 1250.5, dt.date(2027, 4, 1)),
    ("SYN-1002", "Bolt M6", 12.0, dt.date(2027, 4, 1)),
    ("SYN-1003", "Cover, rear", 880.0, dt.date(2027, 5, 15)),
]


def _new_book() -> tuple[Workbook, Worksheet]:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "BOM"
    wb.properties.creator = "bom-intelligence synthetic fixture"
    return wb, ws


def _write_table(
    ws: Worksheet, top: int, left: int, header: list[str], rows: Sequence[Sequence[CellValue]]
) -> None:
    for c, text in enumerate(header):
        ws.cell(row=top, column=left + c, value=text)
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            ws.cell(row=top + r, column=left + c, value=value)


def _clean_rows() -> list[list[CellValue]]:
    return [[pn, name, cost, date] for pn, name, cost, date in CLEAN_ROWS]


def excel_clean_table(path: Path) -> None:
    wb, ws = _new_book()
    _write_table(ws, 1, 1, ["Part No", "Part Name", "Unit Price", "SOP"], _clean_rows())
    wb.save(path)


def excel_shifted_header(path: Path) -> None:
    wb, ws = _new_book()
    ws["A1"] = "Synthetic BOM - project X"
    ws["A2"] = "Revision 3"
    _write_table(ws, 5, 3, ["Part No", "Part Name", "Unit Price", "SOP"], _clean_rows())
    wb.save(path)


def excel_alias_variation(path: Path) -> None:
    wb, ws = _new_book()
    rows = [
        [pn, name, f"¥{cost:,.0f}", date.strftime("%Y/%m/%d")]
        for pn, name, cost, date in CLEAN_ROWS
    ]
    _write_table(ws, 1, 1, ["品番", "品名", "量産単価(円)", "納期"], rows)
    wb.save(path)


def excel_merged_header(path: Path) -> None:
    wb, ws = _new_book()
    ws["A1"], ws["B1"], ws["C1"] = "Part No", "Part Name", "Cost"
    ws["C2"], ws["D2"] = "Prototype", "Production"
    ws.merge_cells("A1:A2")
    ws.merge_cells("B1:B2")
    ws.merge_cells("C1:D1")
    for r, (pn, name, cost, _) in enumerate(CLEAN_ROWS, start=3):
        ws.cell(row=r, column=1, value=pn)
        ws.cell(row=r, column=2, value=name)
        ws.cell(row=r, column=3, value=cost * 2)
        ws.cell(row=r, column=4, value=cost)
    wb.save(path)


def excel_multiple_tables(path: Path) -> None:
    wb, ws = _new_book()
    _write_table(ws, 1, 1, ["Part No", "Part Name", "Unit Price"], [r[:3] for r in _clean_rows()])
    _write_table(
        ws,
        1,
        5,
        ["Part No", "Supplier", "Unit Price"],
        [["SYN-9001", "Example Supplier B", 45.0], ["SYN-9002", "Example Supplier C", 60.0]],
    )
    wb.save(path)


def excel_multiple_cost_fields(path: Path) -> None:
    wb, ws = _new_book()
    rows: list[list[CellValue]] = [[pn, name, cost * 1.5, cost] for pn, name, cost, _ in CLEAN_ROWS]
    _write_table(ws, 1, 1, ["Part No", "Part Name", "試作単価", "量産単価"], rows)
    wb.save(path)


def excel_multiple_schedule_fields(path: Path) -> None:
    wb, ws = _new_book()
    rows: list[list[CellValue]] = [
        [pn, name, cost, date - dt.timedelta(days=90), date] for pn, name, cost, date in CLEAN_ROWS
    ]
    _write_table(ws, 1, 1, ["Part No", "Part Name", "Unit Price", "出図日", "SOP"], rows)
    wb.save(path)


def excel_hidden_content(path: Path) -> None:
    wb, ws = _new_book()
    _write_table(ws, 1, 1, ["Part No", "Part Name", "Unit Price", "SOP"], _clean_rows())
    ws.column_dimensions["B"].hidden = True
    old = wb.create_sheet("old_prices")
    _write_table(old, 1, 1, ["Part No", "Unit Price"], [["SYN-1001", 999.0]])
    old.sheet_state = "hidden"
    wb.save(path)


def excel_formula_values(path: Path) -> None:
    wb, ws = _new_book()
    _write_table(ws, 1, 1, ["Part No", "Part Name", "Qty", "Unit Price"], [])
    for r, (pn, name, cost, _) in enumerate(CLEAN_ROWS, start=2):
        ws.cell(row=r, column=1, value=pn)
        ws.cell(row=r, column=2, value=name)
        ws.cell(row=r, column=3, value=2)
        ws.cell(row=r, column=4, value=f"={cost}*C{r}")
    wb.save(path)


def excel_no_header(path: Path) -> None:
    wb, ws = _new_book()
    ws["B2"] = "部品番号 SYN-4001 の試作コストは別紙参照"
    ws["B4"] = "担当: 設計部"
    wb.save(path)


def excel_password_protected(path: Path) -> None:
    path.write_bytes(OLE_MAGIC + b"\x00" * 504)


def excel_corrupt(path: Path) -> None:
    path.write_bytes(b"PK\x03\x04 this is not a complete zip archive")


def legacy_xls(path: Path) -> None:
    path.write_bytes(OLE_MAGIC + b"\x00" * 504)


def pdf_placeholder(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\n% synthetic placeholder\n%%EOF\n")


def _png(width: int = 4, height: int = 4) -> bytes:
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _blank_slide(prs: object) -> object:
    return prs.slides.add_slide(prs.slide_layouts[6])  # type: ignore[attr-defined]


def _textbox(slide: object, left: float, top: float, text: str) -> None:
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(2), Inches(0.4))  # type: ignore[attr-defined]
    box.text_frame.text = text
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(14)


def ppt_native_table(path: Path) -> None:
    prs = Presentation()
    slide = _blank_slide(prs)
    header = ["品番", "品名", "単価", "納期"]
    rows = [[pn, name, f"{cost:.1f}", d.isoformat()] for pn, name, cost, d in CLEAN_ROWS]
    shape = slide.shapes.add_table(  # type: ignore[attr-defined]
        len(rows) + 1, len(header), Inches(0.5), Inches(1), Inches(8), Inches(2)
    )
    for c, text in enumerate(header):
        shape.table.cell(0, c).text = text
    for r, row in enumerate(rows, start=1):
        for c, text in enumerate(row):
            shape.table.cell(r, c).text = text
    prs.save(str(path))


def ppt_freeform_text(path: Path) -> None:
    prs = Presentation()
    slide = _blank_slide(prs)
    _textbox(slide, 0.5, 0.5, "品番")
    _textbox(slide, 3.0, 0.5, "SYN-3001")
    _textbox(slide, 0.5, 1.5, "試作単価")
    _textbox(slide, 3.0, 1.5, "¥980")
    _textbox(slide, 0.5, 2.5, "納期: 2027/06/30")
    prs.save(str(path))


def ppt_grouped_shapes(path: Path) -> None:
    prs = Presentation()
    slide = _blank_slide(prs)
    group = slide.shapes.add_group_shape()  # type: ignore[attr-defined]
    for i, (label, value) in enumerate([("Part No", "SYN-5001"), ("Cost", "$15.20")]):
        lbl = group.shapes.add_textbox(Inches(0.5), Inches(0.5 + i), Inches(2), Inches(0.4))
        lbl.text_frame.text = label
        val = group.shapes.add_textbox(Inches(3.0), Inches(0.5 + i), Inches(2), Inches(0.4))
        val.text_frame.text = value
    prs.save(str(path))


def ppt_image_heavy(path: Path) -> None:
    prs = Presentation()
    slide = _blank_slide(prs)
    slide.shapes.add_picture(  # type: ignore[attr-defined]
        io.BytesIO(_png()), Emu(0), Emu(0), prs.slide_width, prs.slide_height
    )
    prs.save(str(path))


def ppt_embedded_object(path: Path) -> None:
    buffer = io.BytesIO()
    wb, ws = _new_book()
    _write_table(ws, 1, 1, ["Part No", "Unit Price"], [["SYN-6001", 10.0]])
    wb.save(buffer)
    prs = Presentation()
    slide = _blank_slide(prs)
    _textbox(slide, 0.5, 0.3, "Attached sheet")
    slide.shapes.add_ole_object(  # type: ignore[attr-defined]
        io.BytesIO(buffer.getvalue()), "Excel.Sheet.12", Inches(1), Inches(1)
    )
    chart_data = CategoryChartData()  # type: ignore[no-untyped-call]
    chart_data.categories = ["Q1", "Q2"]
    chart_data.add_series("Volume", (1.0, 2.0))  # type: ignore[no-untyped-call]
    slide.shapes.add_chart(  # type: ignore[attr-defined]
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(5), Inches(1), Inches(4), Inches(3), chart_data
    )
    prs.save(str(path))


Builder = Callable[[Path], None]

FIXTURES: dict[str, Builder] = {
    "excel/clean_table.xlsx": excel_clean_table,
    "excel/shifted_header.xlsx": excel_shifted_header,
    "excel/alias_variation.xlsx": excel_alias_variation,
    "excel/merged_header.xlsx": excel_merged_header,
    "excel/multiple_tables.xlsx": excel_multiple_tables,
    "excel/multiple_cost_fields.xlsx": excel_multiple_cost_fields,
    "excel/multiple_schedule_fields.xlsx": excel_multiple_schedule_fields,
    "excel/hidden_content.xlsx": excel_hidden_content,
    "excel/formula_values.xlsx": excel_formula_values,
    "excel/no_header.xlsx": excel_no_header,
    "excel/password_protected.xlsx": excel_password_protected,
    "excel/corrupt.xlsx": excel_corrupt,
    "excel/legacy.xls": legacy_xls,
    "powerpoint/native_table.pptx": ppt_native_table,
    "powerpoint/freeform_text.pptx": ppt_freeform_text,
    "powerpoint/grouped_shapes.pptx": ppt_grouped_shapes,
    "powerpoint/image_heavy.pptx": ppt_image_heavy,
    "powerpoint/embedded_object.pptx": ppt_embedded_object,
    "other/scan.pdf": pdf_placeholder,
}


def build_fixtures(output: Path, names: list[str] | None = None) -> list[Path]:
    """Write synthetic fixtures under ``output``; returns the written paths."""
    written: list[Path] = []
    for name in names or sorted(FIXTURES):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        FIXTURES[name](target)
        written.append(target)
    return written
