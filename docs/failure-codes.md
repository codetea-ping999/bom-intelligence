# Failure codes

Machine-readable codes are stable; descriptions may evolve. Codes are defined in
`src/bom_intelligence/models/diagnostics.py`; a test keeps this table in sync.

Each diagnostic also carries a severity (`error` blocks deterministic extraction,
`warning`/`info` do not), evidence locations, optional candidate values, and a
suggested next strategy (`rule`, `semantic`, `ocr`, `human_review`, `unsupported`).

| Code | Group | Meaning |
|---|---|---|
| `UNSUPPORTED_FORMAT` | access | No adapter exists for this file format yet. |
| `UNREADABLE_FILE` | access | The file could not be opened or parsed (corrupt, truncated, or wrong format). |
| `PASSWORD_PROTECTED` | access | The file is encrypted / password protected and cannot be inspected. |
| `HEADER_NOT_FOUND` | semantic | No row/table contains recognizable BOM header labels. |
| `HEADER_VARIATION` | semantic | Header labels only partially match known aliases (extra words, variants). |
| `SHIFTED_LAYOUT` | structural | The table does not start at A1, so fixed-position macros read the wrong cells. |
| `MERGED_LAYOUT` | structural | Merged cells overlap the table, breaking one-row-per-record semantics. |
| `MULTIPLE_TABLES` | structural | More than one candidate table exists in the same sheet/slide. |
| `MULTIPLE_PART_FIELDS` | semantic | More than one column/field looks like a part number. |
| `MULTIPLE_COST_FIELDS` | semantic | More than one column/field looks like a cost; which one is meant is unclear. |
| `MULTIPLE_SCHEDULE_FIELDS` | semantic | More than one column/field looks like a schedule date. |
| `SEMANTIC_AMBIGUITY` | semantic | Values exist but their meaning cannot be determined structurally. |
| `FREEFORM_LAYOUT` | structural | BOM labels are placed in free-form text boxes/shapes rather than a table. |
| `HIDDEN_CONTENT` | structural | Hidden sheets, rows, or columns contain content that may matter. |
| `IMAGE_ONLY` | structural | Content appears to be images only; text is not machine-readable without OCR. |
| `EMBEDDED_OBJECT` | structural | Embedded/OLE objects hold content that is not inspected. |
| `FORMULA_DEPENDENCY` | structural | Values are formulas; results depend on cached values or recalculation. |
| `EXTERNAL_LINK_DEPENDENCY` | structural | Values depend on links to other workbooks that are not available. |
| `UNKNOWN` | unknown | Not yet classified. Evidence is kept for taxonomy refinement. |

Groups: **access** = the file cannot be opened; **structural** = layout breaks
fixed-position extraction; **semantic** = the meaning of labels/values is unclear;
**unknown** = not classified yet (evidence is retained for refinement).
