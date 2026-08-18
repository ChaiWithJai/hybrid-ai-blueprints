"""Reproducible end-to-end benchmark for Prism's bounded XLSX display contract."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from core.doc_parser import DealRoomParser


def _dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_workbook(path: Path, cases: list[dict[str, Any]]) -> None:
    """Build a minimal OOXML workbook from benchmark inputs, never expectations."""
    formats: list[str] = []
    for case in cases:
        code = str(case["format_code"])
        if code not in formats:
            formats.append(code)
    format_ids = {code: 164 + index for index, code in enumerate(formats)}
    style_ids = {code: index + 1 for index, code in enumerate(formats)}
    num_formats = "".join(
        f"<numFmt numFmtId={quoteattr(str(format_ids[code]))} "
        f"formatCode={quoteattr(code)}/>" for code in formats
    )
    cell_styles = '<xf numFmtId="0"/>' + "".join(
        f'<xf numFmtId="{format_ids[code]}" applyNumberFormat="1"/>'
        for code in formats
    )
    rows = [
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Case</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Observed value</t></is></c></row>'
    ]
    for row_number, case in enumerate(cases, start=2):
        label = escape(str(case["case_id"]))
        style = style_ids[str(case["format_code"])]
        formula = case.get("formula")
        value = case.get("raw_value")
        formula_xml = f"<f>{escape(str(formula))}</f>" if formula else ""
        value_xml = f"<v>{escape(str(value))}</v>" if value is not None else ""
        rows.append(
            f'<row r="{row_number}"><c r="A{row_number}" t="inlineStr"><is><t>{label}</t></is></c>'
            f'<c r="B{row_number}" s="{style}">{formula_xml}{value_xml}</c></row>'
        )

    members = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/></Types>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Display Contract" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>'
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<numFmts count="{len(formats)}">{num_formats}</numFmts>'
            f'<cellXfs count="{len(formats) + 1}">{cell_styles}</cellXfs></styleSheet>'
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(rows)}</sheetData></worksheet>'
        ),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def evaluate_xlsx_display_benchmark(dataset_path: Path, *, mutate_case: str | None = None) -> dict[str, Any]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = deepcopy(dataset.get("cases", []))
    if mutate_case:
        for case in cases:
            if case.get("case_id") == mutate_case:
                case["expected_display"] = f"WRONG::{case.get('expected_display', '')}"
                break
        else:
            raise ValueError(f"unknown mutation case: {mutate_case}")

    with tempfile.TemporaryDirectory(prefix="prism-xlsx-benchmark-") as folder:
        workbook_path = Path(folder) / "display-contract.xlsx"
        _write_workbook(workbook_path, cases)
        document = DealRoomParser().parse_file(str(workbook_path))

    table = document.extracted_tables[0]
    labels_by_row = {
        cell.row: cell.text for cell in table.cells if cell.col == 0 and cell.row > 0
    }
    by_case = {
        labels_by_row[cell.row]: cell
        for cell in table.cells
        if cell.col == 1 and cell.row in labels_by_row
    }

    results = []
    for case in cases:
        observed = by_case.get(str(case["case_id"]))
        checks = {
            "cell_present": observed is not None,
            "raw_value": observed is not None and observed.metadata.get("raw_value") == case.get("raw_value"),
            "display_value": observed is not None and observed.text == case.get("expected_display"),
            "number_format": observed is not None and observed.metadata.get("number_format_code") == case.get("format_code"),
            "formatting_state": observed is not None and observed.metadata.get("formatting_state") == case.get("expected_formatting_state"),
            "formula": observed is not None and observed.metadata.get("formula") == (
                f"={case['formula']}" if case.get("formula") else None
            ),
            "calculation_state": observed is not None and observed.metadata.get("calculation_state") == case.get("expected_calculation_state"),
        }
        results.append({
            "case_id": case["case_id"],
            "passed": all(checks.values()),
            "checks": checks,
            "expected_display": case.get("expected_display"),
            "observed_display": observed.text if observed is not None else None,
        })

    return {
        "benchmark_id": dataset.get("benchmark_id"),
        "measurement_state": dataset.get("measurement_state"),
        "dataset_sha256": _dataset_sha256(dataset_path),
        "total_cases": len(results),
        "passed_cases": sum(item["passed"] for item in results),
        "pass_rate": (sum(item["passed"] for item in results) / len(results)) if results else 0.0,
        "passed": bool(results) and all(item["passed"] for item in results),
        "cases": results,
        "limitations": dataset.get("limitations", []),
    }
