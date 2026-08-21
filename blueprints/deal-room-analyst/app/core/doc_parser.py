"""Local parser for text, tabular, HTML, JSON, XLSX, and bounded PDF deal files.

This is an internal schema and parser. On the measured macOS prototype, it can
apply Apple Vision OCR to PDF pages without usable embedded text. It does not
promise lossless layout preservation or table reconstruction. Every admitted
document receives a content hash, and HTML/PDF nodes receive stable source
anchors for downstream citations.
"""

import os
import csv
import hashlib
import json
import posixpath
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Dict, Any, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET

from core.macos_ocr import OCR_RENDER_DPI, ocr_pdf_page, ocr_toolchain_status


@dataclass
class TableCell:
    row: int
    col: int
    text: str
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedTable:
    id: str
    caption: str
    num_rows: int
    num_cols: int
    cells: List[TableCell] = field(default_factory=list)
    raw_csv: Optional[str] = None

    def to_matrix(self) -> List[List[str]]:
        matrix = [["" for _ in range(self.num_cols)] for _ in range(self.num_rows)]
        for cell in self.cells:
            if 0 <= cell.row < self.num_rows and 0 <= cell.col < self.num_cols:
                matrix[cell.row][cell.col] = cell.text
        return matrix

    def to_markdown(self) -> str:
        matrix = self.to_matrix()
        if not matrix:
            return ""
        lines = []
        # Header row
        header = "| " + " | ".join(matrix[0]) + " |"
        separator = "| " + " | ".join(["---" for _ in matrix[0]]) + " |"
        lines.append(header)
        lines.append(separator)
        for row in matrix[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


@dataclass
class ParsedNode:
    id: str
    node_type: str  # 'document', 'section', 'paragraph', 'table', 'code_block', 'metadata'
    title: Optional[str] = None
    content: Optional[str] = None
    table_data: Optional[ParsedTable] = None
    children: List['ParsedNode'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    doc_id: str
    filename: str
    file_path: str
    file_type: str
    raw_size_bytes: int
    estimated_token_count: int
    root_node: ParsedNode
    extracted_tables: List[ParsedTable] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def evidence_node_text(
    node: ParsedNode,
    section_titles: Sequence[str] = (),
    max_chars: int | None = None,
) -> str:
    """Render one citation passage with its containing section labels."""
    parts = [str(title) for title in section_titles if title]
    parts.extend(str(value) for value in (node.title, node.content) if value)
    if node.table_data is not None:
        parts.append(node.table_data.to_markdown())
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return text[:max_chars] if max_chars is not None else text


def iter_evidence_nodes(
    node: ParsedNode,
    section_titles: Tuple[str, ...] = (),
) -> Iterable[tuple[ParsedNode, Tuple[str, ...]]]:
    """Yield factual nodes while carrying their section hierarchy.

    Title-only document and section nodes remain navigable in the workspace,
    but are not independently admitted as factual evidence. Their titles are
    inherited by child paragraphs and tables instead.
    """
    has_body = bool(node.content or node.table_data is not None)
    if node.node_type not in {"document", "section"} or has_body:
        yield node, section_titles
    child_titles = section_titles
    if node.node_type == "section" and node.title:
        child_titles = (*section_titles, str(node.title))
    for child in node.children:
        yield from iter_evidence_nodes(child, child_titles)


class _DealHTMLExtractor(HTMLParser):
    """Extract readable blocks and tables without trusting active HTML content."""

    _BLOCK_TAGS = {"p", "div", "li", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[tuple[str, str]] = []
        self.tables: List[ParsedTable] = []
        self._skip_depth = 0
        self._table_depth = 0
        self._active_block_tag: Optional[str] = None
        self._active_block_text: List[str] = []
        self._table_rows: List[List[tuple[str, bool]]] = []
        self._active_row: List[tuple[str, bool]] = []
        self._active_cell: Optional[List[str]] = None
        self._active_cell_header = False

    @staticmethod
    def _clean(parts: List[str]) -> str:
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def _flush_block(self) -> None:
        text = self._clean(self._active_block_text)
        if text:
            self.blocks.append((self._active_block_tag or "div", text))
        self._active_block_tag = None
        self._active_block_text = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "table":
            self._flush_block()
            self._table_depth += 1
            if self._table_depth == 1:
                self._table_rows = []
            return
        if self._table_depth:
            if tag == "tr":
                self._active_row = []
            elif tag in {"td", "th"}:
                self._active_cell = []
                self._active_cell_header = tag == "th"
            elif tag == "br" and self._active_cell is not None:
                self._active_cell.append(" ")
            return
        if tag in self._BLOCK_TAGS:
            self._flush_block()
            self._active_block_tag = tag
        elif tag == "br":
            self._active_block_text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if self._table_depth:
            if tag in {"td", "th"} and self._active_cell is not None:
                self._active_row.append((self._clean(self._active_cell), self._active_cell_header))
                self._active_cell = None
            elif tag == "tr" and self._active_row:
                self._table_rows.append(self._active_row)
                self._active_row = []
            elif tag == "table":
                self._table_depth -= 1
                if self._table_depth == 0:
                    self._flush_table()
            return
        if tag in self._BLOCK_TAGS and tag == self._active_block_tag:
            self._flush_block()

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data.strip():
            return
        if self._table_depth:
            if self._active_cell is not None:
                self._active_cell.append(data)
            return
        self._active_block_text.append(data)

    def _flush_table(self) -> None:
        if not self._table_rows:
            return
        table_id = f"html_table_{len(self.tables) + 1:04d}"
        num_cols = max((len(row) for row in self._table_rows), default=0)
        cells = [
            TableCell(row=row_index, col=col_index, text=text, is_header=is_header or row_index == 0)
            for row_index, row in enumerate(self._table_rows)
            for col_index, (text, is_header) in enumerate(row)
        ]
        self.tables.append(ParsedTable(
            id=table_id,
            caption=f"HTML table {len(self.tables) + 1}",
            num_rows=len(self._table_rows),
            num_cols=num_cols,
            cells=cells,
        ))
        self._table_rows = []

    def close(self) -> None:
        super().close()
        self._flush_block()


class DealRoomParser:
    """
    Parses bounded local deal-room files into a source-bound internal schema.

    XLSX support reads stored workbook values and applies a bounded, audited
    subset of number formats. It does not execute macros, follow external
    links, recalculate formulas, or provide full Excel formatting parity.
    """

    def __init__(
        self,
        chars_per_token: float = 4.0,
        max_file_bytes: int = 10 * 1024 * 1024,
        *,
        enable_pdf_ocr: bool = True,
        max_ocr_pages: int = 200,
        min_pdf_text_chars: int = 12,
    ):
        self.chars_per_token = chars_per_token
        self.max_file_bytes = max_file_bytes
        self.enable_pdf_ocr = enable_pdf_ocr
        self.max_ocr_pages = max_ocr_pages
        self.min_pdf_text_chars = min_pdf_text_chars
        self.last_warnings: List[Dict[str, str]] = []
        self.max_xlsx_members = 2_048
        self.max_xlsx_uncompressed_bytes = min(max_file_bytes * 20, 100 * 1024 * 1024)
        self.max_xlsx_member_bytes = min(max_file_bytes * 4, 20 * 1024 * 1024)
        self.max_xlsx_sheets = 64
        self.max_xlsx_rows = 5_000
        self.max_xlsx_cols = 256
        self.max_xlsx_cells = 50_000
        self.max_folder_files = 512
        self.max_folder_depth = 8
        self.max_folder_bytes = 100 * 1024 * 1024

    def parse_file(self, file_path: str) -> ParsedDocument:
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        if file_size > self.max_file_bytes:
            raise ValueError(f"File exceeds {self.max_file_bytes} byte parser limit")
        ext = os.path.splitext(filename)[1].lower()

        if ext in ['.md', '.txt']:
            return self._parse_markdown(file_path, filename, file_size)
        elif ext in ['.htm', '.html']:
            return self._parse_html(file_path, filename, file_size)
        elif ext == '.pdf':
            return self._parse_pdf(file_path, filename, file_size)
        elif ext == '.csv':
            return self._parse_csv(file_path, filename, file_size)
        elif ext == '.json':
            return self._parse_json(file_path, filename, file_size)
        elif ext == '.xlsx':
            return self._parse_xlsx(file_path, filename, file_size)
        else:
            raise ValueError(f"Unsupported file type: {ext or '[no extension]'}")

    @staticmethod
    def _source_metadata(file_path: str) -> Dict[str, Any]:
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"source_sha256": digest.hexdigest()}

    def _parse_markdown(self, file_path: str, filename: str, file_size: int) -> ParsedDocument:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        estimated_tokens = int(len(content) / self.chars_per_token)
        root = ParsedNode(id=f"root_{filename}", node_type="document", title=filename)
        tables = []

        lines = content.split('\n')
        current_section = root
        current_text_buf = []
        table_buf = []
        in_table = False
        paragraph_count = 0

        for line_idx, line in enumerate(lines):
            stripped = line.strip()

            # Heading Detection
            if stripped.startswith('#'):
                if in_table and table_buf:
                    tbl = self._parse_markdown_table(table_buf, f"tbl_{len(tables)+1}")
                    if tbl:
                        tables.append(tbl)
                        current_section.children.append(ParsedNode(
                            id=f"node_tbl_{len(tables)}",
                            node_type="table",
                            table_data=tbl
                        ))
                    table_buf = []
                    in_table = False

                if current_text_buf:
                    paragraph_count += 1
                    current_section.children.append(ParsedNode(
                        id=f"node_para_{paragraph_count}",
                        node_type="paragraph",
                        content="\n".join(current_text_buf)
                    ))
                    current_text_buf = []

                level = len(stripped) - len(stripped.lstrip('#'))
                title = stripped.lstrip('#').strip()
                sec_node = ParsedNode(
                    id=f"sec_{len(root.children)+1}_{level}",
                    node_type="section",
                    title=title,
                    metadata={"heading_level": level}
                )
                root.children.append(sec_node)
                current_section = sec_node
                continue

            # Markdown Table Detection
            if stripped.startswith('|') and stripped.endswith('|'):
                in_table = True
                table_buf.append(stripped)
                continue
            else:
                if in_table and table_buf:
                    tbl = self._parse_markdown_table(table_buf, f"tbl_{len(tables)+1}")
                    if tbl:
                        tables.append(tbl)
                        current_section.children.append(ParsedNode(
                            id=f"node_tbl_{len(tables)}",
                            node_type="table",
                            table_data=tbl
                        ))
                    table_buf = []
                    in_table = False

            if stripped:
                current_text_buf.append(line)

        # Flush remaining buffers
        if in_table and table_buf:
            tbl = self._parse_markdown_table(table_buf, f"tbl_{len(tables)+1}")
            if tbl:
                tables.append(tbl)
                current_section.children.append(ParsedNode(
                    id=f"node_tbl_{len(tables)}",
                    node_type="table",
                    table_data=tbl
                ))

        if current_text_buf:
            paragraph_count += 1
            current_section.children.append(ParsedNode(
                id=f"node_para_{paragraph_count}",
                node_type="paragraph",
                content="\n".join(current_text_buf)
            ))

        return ParsedDocument(
            doc_id=filename.replace('.', '_'),
            filename=filename,
            file_path=file_path,
            file_type="markdown",
            raw_size_bytes=file_size,
            estimated_token_count=estimated_tokens,
            root_node=root,
            extracted_tables=tables,
            metadata=self._source_metadata(file_path),
        )

    def _parse_html(self, file_path: str, filename: str, file_size: int) -> ParsedDocument:
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
        extractor = _DealHTMLExtractor()
        extractor.feed(content)
        extractor.close()

        root = ParsedNode(id=f"root_{filename}", node_type="document", title=filename)
        current_section = root
        for index, (tag, text) in enumerate(extractor.blocks, start=1):
            anchor = f"html:block:{index:05d}"
            if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
                node = ParsedNode(
                    id=f"html_section_{index:05d}", node_type="section", title=text,
                    metadata={"heading_level": int(tag[1]), "source_anchor": anchor},
                )
                root.children.append(node)
                current_section = node
            else:
                current_section.children.append(ParsedNode(
                    id=f"html_block_{index:05d}", node_type="paragraph", content=text,
                    metadata={"html_tag": tag, "source_anchor": anchor},
                ))
        for index, table in enumerate(extractor.tables, start=1):
            root.children.append(ParsedNode(
                id=f"html_table_node_{index:04d}", node_type="table", table_data=table,
                metadata={"source_anchor": f"html:table:{index:04d}"},
            ))

        metadata = self._source_metadata(file_path)
        metadata.update({
            "citation_scheme": "filename + html:block|table anchor",
            "html_block_count": len(extractor.blocks),
            "html_table_count": len(extractor.tables),
        })
        return ParsedDocument(
            doc_id=filename.replace('.', '_'), filename=filename, file_path=file_path,
            file_type="html", raw_size_bytes=file_size,
            estimated_token_count=int(sum(len(text) for _, text in extractor.blocks) / self.chars_per_token),
            root_node=root, extracted_tables=extractor.tables, metadata=metadata,
        )

    def _parse_pdf(self, file_path: str, filename: str, file_size: int) -> ParsedDocument:
        pdftotext = shutil.which("pdftotext")
        pdfinfo = shutil.which("pdfinfo")
        if not pdftotext or not pdfinfo:
            raise ValueError("PDF parsing requires Poppler commands pdftotext and pdfinfo")
        try:
            info = subprocess.run(
                [pdfinfo, file_path], capture_output=True, text=True, timeout=60, check=True,
            ).stdout
            extracted = subprocess.run(
                [pdftotext, "-layout", file_path, "-"], capture_output=True, text=True,
                timeout=180, check=True,
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"PDF extraction failed: {exc}") from exc
        match = re.search(r"^Pages:\s+(\d+)$", info, re.MULTILINE)
        declared_pages = int(match.group(1)) if match else None
        pages = extracted.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        if declared_pages is not None:
            pages = pages[:declared_pages]
            pages.extend([""] * max(0, declared_pages - len(pages)))

        def usable_char_count(value: str) -> int:
            return sum(character.isalnum() for character in value)

        ocr_page_numbers = [
            page_number
            for page_number, page_text in enumerate(pages, start=1)
            if usable_char_count(page_text) < self.min_pdf_text_chars
        ]
        if ocr_page_numbers and not self.enable_pdf_ocr:
            if not any(usable_char_count(page) >= self.min_pdf_text_chars for page in pages):
                raise ValueError(
                    "PDF has no usable embedded text and PDF OCR is disabled"
                )
            ocr_page_numbers = []
        if len(ocr_page_numbers) > self.max_ocr_pages:
            raise ValueError(
                f"PDF requires OCR on {len(ocr_page_numbers)} pages, which exceeds the "
                f"{self.max_ocr_pages} page OCR limit"
            )

        ocr_status = ocr_toolchain_status()
        if ocr_page_numbers and not ocr_status["available"]:
            if not any(usable_char_count(page) >= self.min_pdf_text_chars for page in pages):
                raise ValueError(
                    "PDF has no usable embedded text and the macOS Vision OCR toolchain is unavailable"
                )
            ocr_page_numbers = []

        ocr_results: Dict[int, Dict[str, Any]] = {}
        for page_number in ocr_page_numbers:
            try:
                result = ocr_pdf_page(Path(file_path), page_number)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                raise ValueError(f"PDF OCR failed on page {page_number}: {exc}") from exc
            ocr_text = str(result.get("text", "")).strip()
            if usable_char_count(ocr_text) > usable_char_count(pages[page_number - 1]):
                pages[page_number - 1] = ocr_text
                ocr_results[page_number] = result

        if not any(usable_char_count(page) >= self.min_pdf_text_chars for page in pages):
            raise ValueError("PDF extraction produced no usable text")

        root = ParsedNode(id=f"root_{filename}", node_type="document", title=filename)
        for page_number, page_text in enumerate(pages, start=1):
            cleaned = page_text.strip()
            page_metadata: Dict[str, Any] = {
                "page_number": page_number,
                "source_anchor": f"pdf:page:{page_number}",
                "text_extraction": "ocr" if page_number in ocr_results else "pdftotext",
            }
            if page_number in ocr_results:
                page_metadata["ocr_mean_confidence"] = ocr_results[page_number].get(
                    "meanConfidence"
                )
            root.children.append(ParsedNode(
                id=f"pdf_page_{page_number:04d}", node_type="section",
                title=f"Page {page_number}", content=cleaned,
                metadata=page_metadata,
            ))
        ocr_confidences = [
            float(result["meanConfidence"])
            for result in ocr_results.values()
            if isinstance(result.get("meanConfidence"), (int, float))
        ]
        metadata = self._source_metadata(file_path)
        metadata.update({
            "citation_scheme": "filename + PDF page number",
            "declared_page_count": declared_pages,
            "extracted_page_count": len(pages),
            "ocr_applied": bool(ocr_results),
            "ocr_page_numbers": sorted(ocr_results),
            "ocr_engine": (
                "apple_vision_vnrecognizetextrequest" if ocr_results else None
            ),
            "ocr_render_dpi": OCR_RENDER_DPI if ocr_results else None,
            "ocr_recognition_level": "accurate" if ocr_results else None,
            "ocr_language_correction": True if ocr_results else None,
            "ocr_mean_confidence": (
                sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else None
            ),
            "ocr_accuracy_measured": False,
            "ocr_layout_reconstruction": False,
            "ocr_limitations": ocr_status["limitations"] if ocr_results else [],
        })
        return ParsedDocument(
            doc_id=filename.replace('.', '_'), filename=filename, file_path=file_path,
            file_type="pdf", raw_size_bytes=file_size,
            estimated_token_count=int(sum(len(page) for page in pages) / self.chars_per_token),
            root_node=root, extracted_tables=[], metadata=metadata,
        )

    def _parse_markdown_table(self, lines: List[str], table_id: str) -> Optional[ParsedTable]:
        if len(lines) < 2:
            return None
        rows = []
        for l in lines:
            # Skip separator line like | :--- | :--- |
            if re.match(r'^\|[\s\:\-\|]+\|$', l.strip()):
                continue
            cells_raw = [c.strip() for c in l.strip()[1:-1].split('|')]
            rows.append(cells_raw)

        if not rows:
            return None

        num_rows = len(rows)
        num_cols = max(len(r) for r in rows)
        ast_cells = []

        for r_idx, row in enumerate(rows):
            for c_idx, cell_text in enumerate(row):
                ast_cells.append(TableCell(
                    row=r_idx,
                    col=c_idx,
                    text=cell_text,
                    is_header=(r_idx == 0)
                ))

        return ParsedTable(
            id=table_id,
            caption=f"Extracted Table {table_id}",
            num_rows=num_rows,
            num_cols=num_cols,
            cells=ast_cells,
            raw_csv="\n".join([",".join([f'"{c}"' for c in r]) for r in rows])
        )

    def _parse_csv(self, file_path: str, filename: str, file_size: int) -> ParsedDocument:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        reader = csv.reader(content.splitlines())
        rows = list(reader)
        estimated_tokens = int(len(content) / self.chars_per_token)

        tables = []
        if rows:
            num_rows = len(rows)
            num_cols = max((len(row) for row in rows), default=0)
            ast_cells = []
            for r_idx, row in enumerate(rows):
                for c_idx, val in enumerate(row):
                    ast_cells.append(TableCell(
                        row=r_idx,
                        col=c_idx,
                        text=val.strip(),
                        is_header=(r_idx == 0)
                    ))
            tbl = ParsedTable(
                id=f"tbl_{filename}",
                caption=f"Consolidated Ledger Table ({filename})",
                num_rows=num_rows,
                num_cols=num_cols,
                cells=ast_cells,
                raw_csv=content
            )
            tables.append(tbl)

        root = ParsedNode(
            id=f"root_{filename}",
            node_type="document",
            title=filename,
            children=[
                ParsedNode(
                    id="node_csv_table",
                    node_type="table",
                    title="Financial Ledger",
                    table_data=tables[0] if tables else None
                )
            ]
        )

        return ParsedDocument(
            doc_id=filename.replace('.', '_'),
            filename=filename,
            file_path=file_path,
            file_type="csv",
            raw_size_bytes=file_size,
            estimated_token_count=estimated_tokens,
            root_node=root,
            extracted_tables=tables,
            metadata=self._source_metadata(file_path),
        )

    def _parse_json(self, file_path: str, filename: str, file_size: int) -> ParsedDocument:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()

        data = json.loads(raw_content)
        estimated_tokens = int(len(raw_content) / self.chars_per_token)

        root = ParsedNode(
            id=f"root_{filename}",
            node_type="document",
            title=filename,
            metadata={
                "json_root_type": type(data).__name__,
                "raw_json_keys": list(data.keys()) if isinstance(data, dict) else [],
            }
        )

        items = data.items() if isinstance(data, dict) else [("root", data)]
        for key, val in items:
            child_content = json.dumps(val, indent=2) if isinstance(val, (dict, list)) else str(val)
            root.children.append(ParsedNode(
                id=f"sec_{key}",
                node_type="section",
                title=key.replace('_', ' ').title(),
                content=child_content
            ))

        return ParsedDocument(
            doc_id=filename.replace('.', '_'),
            filename=filename,
            file_path=file_path,
            file_type="json",
            raw_size_bytes=file_size,
            estimated_token_count=estimated_tokens,
            root_node=root,
            extracted_tables=[],
            metadata=self._source_metadata(file_path),
        )

    @staticmethod
    def _xlsx_column_index(reference: str) -> tuple[int, int]:
        match = re.fullmatch(r"([A-Za-z]+)([1-9][0-9]*)", reference)
        if not match:
            raise ValueError(f"XLSX cell has invalid coordinate: {reference!r}")
        column = 0
        for character in match.group(1).upper():
            column = column * 26 + ord(character) - ord("A") + 1
        return int(match.group(2)) - 1, column - 1

    def _read_xlsx_member(self, archive: zipfile.ZipFile, name: str) -> bytes:
        try:
            member = archive.getinfo(name)
        except KeyError as exc:
            raise ValueError(f"XLSX is missing required member: {name}") from exc
        if member.file_size > self.max_xlsx_member_bytes:
            raise ValueError(f"XLSX member exceeds parser limit: {name}")
        return archive.read(member)

    @staticmethod
    def _xlsx_text(element: ET.Element) -> str:
        return "".join(node.text or "" for node in element.iter() if node.tag.endswith("}t"))

    @staticmethod
    def _xlsx_style_formats(
        archive: zipfile.ZipFile,
        read_member,
        spreadsheet_ns: str,
    ) -> List[Optional[str]]:
        """Return the number-format code for each cell style index."""
        if "xl/styles.xml" not in archive.namelist():
            return [None]
        builtins = {
            0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00",
            9: "0%", 10: "0.00%", 11: "0.00E+00",
            14: "mm-dd-yy", 49: "@",
        }
        styles = ET.fromstring(read_member(archive, "xl/styles.xml"))
        custom = {
            int(item.attrib["numFmtId"]): item.attrib.get("formatCode", "")
            for item in styles.findall(f".//{{{spreadsheet_ns}}}numFmt")
            if item.attrib.get("numFmtId", "").isdigit()
        }
        cell_xfs = styles.find(f"{{{spreadsheet_ns}}}cellXfs")
        if cell_xfs is None:
            return [None]
        return [
            custom.get(int(item.attrib.get("numFmtId", "0")),
                       builtins.get(int(item.attrib.get("numFmtId", "0"))))
            for item in cell_xfs.findall(f"{{{spreadsheet_ns}}}xf")
        ] or [None]

    @staticmethod
    def _format_xlsx_number(raw_value: str, format_code: Optional[str]) -> tuple[str, str]:
        """Format a small audited subset; return raw text for every other pattern."""
        if not format_code or format_code == "General":
            return raw_value, "raw_general"
        if ";" in format_code or "[" in format_code or "]" in format_code:
            return raw_value, "raw_unsupported_format"
        normalized = format_code.replace('"', "")
        suffix = ""
        scale = Decimal("1")
        if normalized.endswith("%"):
            suffix = "%"
            scale = Decimal("100")
            numeric_pattern = normalized[:-1]
        elif normalized.endswith(r"\x") or normalized.endswith("x"):
            suffix = "x"
            numeric_pattern = normalized[:-2] if normalized.endswith(r"\x") else normalized[:-1]
        else:
            numeric_pattern = normalized
        currency = numeric_pattern.startswith(r"\$") or numeric_pattern.startswith("$")
        if currency:
            numeric_pattern = numeric_pattern[2:] if numeric_pattern.startswith(r"\$") else numeric_pattern[1:]
        supported = {"0", "0.0", "0.00", "0.000", "0.0000", "#,##0", "#,##0.0", "#,##0.00"}
        if numeric_pattern not in supported:
            return raw_value, "raw_unsupported_format"
        decimals = len(numeric_pattern.split(".", 1)[1]) if "." in numeric_pattern else 0
        grouping = "," in numeric_pattern
        try:
            number = Decimal(raw_value) * scale
        except InvalidOperation:
            return raw_value, "raw_invalid_numeric_value"
        rendered = format(number, f"{',' if grouping else ''}.{decimals}f")
        return f"{'$' if currency else ''}{rendered}{suffix}", "display_format_applied"

    def _parse_xlsx(self, file_path: str, filename: str, file_size: int) -> ParsedDocument:
        spreadsheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        office_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"

        try:
            archive = zipfile.ZipFile(file_path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError(f"Invalid XLSX archive: {exc}") from exc

        with archive:
            members = archive.infolist()
            if len(members) > self.max_xlsx_members:
                raise ValueError("XLSX archive contains too many members")
            if sum(member.file_size for member in members) > self.max_xlsx_uncompressed_bytes:
                raise ValueError("XLSX uncompressed content exceeds parser limit")
            for member in members:
                path = PurePosixPath(member.filename)
                if member.flag_bits & 0x1:
                    raise ValueError("Encrypted XLSX members are not supported")
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("XLSX contains an unsafe member path")
                if member.file_size > self.max_xlsx_member_bytes:
                    raise ValueError(f"XLSX member exceeds parser limit: {member.filename}")
                if member.filename.lower().endswith("vbaproject.bin"):
                    raise ValueError("Macro-bearing workbooks are not supported")

            workbook = ET.fromstring(self._read_xlsx_member(archive, "xl/workbook.xml"))
            relationships = ET.fromstring(
                self._read_xlsx_member(archive, "xl/_rels/workbook.xml.rels")
            )
            rel_targets: Dict[str, str] = {}
            for relationship in relationships.findall(f"{{{package_rel_ns}}}Relationship"):
                if relationship.attrib.get("TargetMode", "").lower() == "external":
                    raise ValueError("XLSX workbook relationships may not target external resources")
                relationship_id = relationship.attrib.get("Id")
                target = relationship.attrib.get("Target", "")
                if target.startswith("/"):
                    normalized = posixpath.normpath(target.lstrip("/"))
                else:
                    normalized = posixpath.normpath(posixpath.join("xl", target))
                if relationship_id and normalized.startswith("xl/worksheets/"):
                    rel_targets[relationship_id] = normalized

            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = ET.fromstring(self._read_xlsx_member(archive, "xl/sharedStrings.xml"))
                shared_strings = [
                    self._xlsx_text(item)
                    for item in shared_root.findall(f"{{{spreadsheet_ns}}}si")
                ]
            style_formats = self._xlsx_style_formats(
                archive, self._read_xlsx_member, spreadsheet_ns,
            )

            sheets = workbook.findall(f".//{{{spreadsheet_ns}}}sheet")
            if len(sheets) > self.max_xlsx_sheets:
                raise ValueError("XLSX workbook contains too many sheets")

            root = ParsedNode(id=f"root_{filename}", node_type="document", title=filename)
            tables: List[ParsedTable] = []
            formula_cells = 0
            unevaluated_formula_cells = 0
            cached_formula_cells = 0
            total_cells = 0
            text_size = 0
            formatted_numeric_cells = 0
            unsupported_format_cells = 0

            for sheet_index, sheet in enumerate(sheets, start=1):
                sheet_name = sheet.attrib.get("name", f"Sheet {sheet_index}")
                relationship_id = sheet.attrib.get(f"{{{office_rel_ns}}}id")
                member_name = rel_targets.get(relationship_id or "")
                if not member_name:
                    raise ValueError(f"XLSX sheet {sheet_name!r} has no internal worksheet target")
                worksheet = ET.fromstring(self._read_xlsx_member(archive, member_name))
                cells: List[TableCell] = []
                max_row = -1
                max_col = -1

                for cell in worksheet.findall(f".//{{{spreadsheet_ns}}}c"):
                    reference = cell.attrib.get("r", "")
                    row_index, col_index = self._xlsx_column_index(reference)
                    if row_index >= self.max_xlsx_rows or col_index >= self.max_xlsx_cols:
                        raise ValueError(
                            f"XLSX cell {sheet_name}!{reference} exceeds the "
                            f"{self.max_xlsx_rows}-row/{self.max_xlsx_cols}-column parser boundary"
                        )
                    total_cells += 1
                    if total_cells > self.max_xlsx_cells:
                        raise ValueError("XLSX workbook contains too many cells")

                    cell_type = cell.attrib.get("t", "n")
                    value_node = cell.find(f"{{{spreadsheet_ns}}}v")
                    formula_node = cell.find(f"{{{spreadsheet_ns}}}f")
                    raw_value = value_node.text if value_node is not None and value_node.text is not None else None
                    metadata: Dict[str, Any] = {
                        "source_anchor": f"xlsx:sheet:{sheet_index}:cell:{reference.upper()}",
                        "sheet_name": sheet_name,
                        "cell_reference": reference.upper(),
                        "stored_type": cell_type,
                    }
                    style_text = cell.attrib.get("s", "0")
                    if not style_text.isdigit() or int(style_text) >= len(style_formats):
                        raise ValueError(
                            f"XLSX cell {sheet_name}!{reference} has an invalid style index"
                        )
                    style_index = int(style_text)
                    number_format = style_formats[style_index]
                    metadata["style_index"] = style_index
                    metadata["number_format_code"] = number_format

                    if cell_type == "inlineStr":
                        inline = cell.find(f"{{{spreadsheet_ns}}}is")
                        text_value = self._xlsx_text(inline) if inline is not None else ""
                    elif cell_type == "s":
                        try:
                            text_value = shared_strings[int(raw_value or "")]
                        except (ValueError, IndexError) as exc:
                            raise ValueError(
                                f"XLSX cell {sheet_name}!{reference} has an invalid shared-string index"
                            ) from exc
                    elif cell_type == "b":
                        text_value = "TRUE" if raw_value == "1" else "FALSE"
                    else:
                        text_value = raw_value or ""

                    if cell_type == "n" and raw_value is not None:
                        text_value, formatting_state = self._format_xlsx_number(
                            raw_value, number_format,
                        )
                        metadata["raw_value"] = raw_value
                        metadata["display_value"] = text_value
                        metadata["formatting_state"] = formatting_state
                        if formatting_state == "display_format_applied":
                            formatted_numeric_cells += 1
                        elif formatting_state == "raw_unsupported_format":
                            unsupported_format_cells += 1
                    elif cell_type == "n":
                        metadata["raw_value"] = None
                        metadata["display_value"] = text_value
                        metadata["formatting_state"] = "not_applicable"

                    if formula_node is not None:
                        formula_cells += 1
                        formula = formula_node.text or ""
                        metadata["formula"] = f"={formula}"
                        if raw_value is None:
                            unevaluated_formula_cells += 1
                            metadata["calculation_state"] = "formula_without_cached_value"
                            text_value = f"[formula not calculated] ={formula}"
                        else:
                            cached_formula_cells += 1
                            metadata["calculation_state"] = "cached_value_not_recalculated"
                    else:
                        metadata["calculation_state"] = "literal_value"

                    text_size += len(text_value)
                    cells.append(TableCell(
                        row=row_index,
                        col=col_index,
                        text=text_value,
                        is_header=(row_index == 0),
                        metadata=metadata,
                    ))
                    max_row = max(max_row, row_index)
                    max_col = max(max_col, col_index)

                table = ParsedTable(
                    id=f"xlsx_sheet_{sheet_index:04d}",
                    caption=sheet_name,
                    num_rows=max_row + 1 if cells else 0,
                    num_cols=max_col + 1 if cells else 0,
                    cells=cells,
                )
                tables.append(table)
                root.children.append(ParsedNode(
                    id=f"xlsx_sheet_node_{sheet_index:04d}",
                    node_type="table",
                    title=sheet_name,
                    table_data=table,
                    metadata={
                        "source_anchor": f"xlsx:sheet:{sheet_index}",
                        "sheet_index": sheet_index,
                        "sheet_name": sheet_name,
                        "sheet_state": sheet.attrib.get("state", "visible"),
                    },
                ))

        metadata = self._source_metadata(file_path)
        metadata.update({
            "citation_scheme": "filename + XLSX sheet index and cell coordinate",
            "sheet_count": len(tables),
            "nonempty_cell_count": total_cells,
            "formula_cell_count": formula_cells,
            "cached_formula_cell_count": cached_formula_cells,
            "unevaluated_formula_cell_count": unevaluated_formula_cells,
            "formula_policy": "stored cached values only; formulas are never recalculated",
            "formatted_numeric_cell_count": formatted_numeric_cells,
            "unsupported_number_format_cell_count": unsupported_format_cells,
            "formatting_policy": (
                "audited percent, fixed-decimal, grouping, currency, and x-multiple formats are "
                "applied; raw values are preserved in cell metadata; other Excel formats remain raw"
            ),
            "external_relationships_followed": False,
            "macros_executed": False,
        })
        return ParsedDocument(
            doc_id=filename.replace('.', '_'),
            filename=filename,
            file_path=file_path,
            file_type="xlsx",
            raw_size_bytes=file_size,
            estimated_token_count=int(text_size / self.chars_per_token),
            root_node=root,
            extracted_tables=tables,
            metadata=metadata,
        )

    def parse_deal_room_folder(self, folder_path: str) -> List[ParsedDocument]:
        """Recursively parse a bounded folder using stable relative source names."""
        docs: List[ParsedDocument] = []
        self.last_warnings = []
        if not os.path.isdir(folder_path):
            return docs
        root = os.path.realpath(folder_path)
        candidate_count = 0
        admitted_bytes = 0
        for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            relative_directory = os.path.relpath(current, root)
            depth = 0 if relative_directory == "." else len(PurePosixPath(relative_directory).parts)
            if depth >= self.max_folder_depth:
                for dirname in sorted(dirnames):
                    relative = os.path.relpath(os.path.join(current, dirname), root).replace(os.sep, "/")
                    self.last_warnings.append({
                        "filename": relative,
                        "error": f"Directory exceeds {self.max_folder_depth} level parser depth limit",
                    })
                dirnames[:] = []
            else:
                admitted_directories = []
                for dirname in sorted(dirnames):
                    directory_path = os.path.join(current, dirname)
                    relative = os.path.relpath(directory_path, root).replace(os.sep, "/")
                    if dirname.startswith("."):
                        continue
                    if os.path.islink(directory_path):
                        self.last_warnings.append({
                            "filename": relative,
                            "error": "Symbolic links are not followed",
                        })
                        continue
                    admitted_directories.append(dirname)
                dirnames[:] = admitted_directories

            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                file_path = os.path.join(current, filename)
                relative = os.path.relpath(file_path, root).replace(os.sep, "/")
                if os.path.islink(file_path):
                    self.last_warnings.append({
                        "filename": relative,
                        "error": "Symbolic links are not followed",
                    })
                    continue
                if not os.path.isfile(file_path):
                    continue
                candidate_count += 1
                if candidate_count > self.max_folder_files:
                    raise ValueError(
                        f"Folder exceeds {self.max_folder_files} visible file parser limit"
                    )
                file_size = os.path.getsize(file_path)
                if file_size > self.max_file_bytes:
                    self.last_warnings.append({
                        "filename": relative,
                        "error": f"File exceeds {self.max_file_bytes} byte parser limit",
                    })
                    continue
                if admitted_bytes + file_size > self.max_folder_bytes:
                    raise ValueError(
                        f"Folder exceeds {self.max_folder_bytes} admitted byte parser limit"
                    )
                try:
                    document = self.parse_file(file_path)
                    document.filename = relative
                    document.metadata["relative_path"] = relative
                    if "/" in relative:
                        document.doc_id = "doc_" + hashlib.sha256(relative.encode()).hexdigest()[:16]
                    docs.append(document)
                    admitted_bytes += file_size
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self.last_warnings.append({"filename": relative, "error": str(exc)})
        return docs
