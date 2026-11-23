"""Source-mapped, dependency-free Office file preview for trusted tool outputs.

Ports the safe, static fallback of LibreChat pinned
packages/api/src/files/documents/{html,zipSafety}.ts: DOCX article, XLSX/ODS/CSV
sheet tables and PPTX slide list. We deliberately do not implement the original
CDN-based DOCX/PPTX renderer: no untrusted active Office markup or external CDN
scripts are placed into the preview. The output is *generated* escaped HTML,
not sanitized HTML supplied by a caller. No runtime Node or LibreOffice binary.
"""
from __future__ import annotations

import csv
import html
import io
import re
import xml.etree.ElementTree as ET
import zlib
from contextlib import contextmanager
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

OFFICE_HTML_OUTPUT_CAP = 512 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_ENTRY_BYTES = 25 * 1024 * 1024
MAX_ROWS = 5000
MAX_SLIDES = 500
MAX_COLUMNS = 256
MAX_VISIBLE_CHARS = 180000

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
POTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.template"
ODS_MIME = "application/vnd.oasis.opendocument.spreadsheet"

_OFFICE_EXTENSIONS = {
    "docx": "docx", "csv": "csv", "xlsx": "spreadsheet", "xls": "spreadsheet",
    "ods": "spreadsheet", "pptx": "presentation", "potx": "presentation",
}


class UnsafeOfficeArchive(ValueError):
    """Upstream ZipBombError parity: do not inflate or preview this archive."""


def office_html_bucket(name: str, mime_type: str) -> str | None:
    """LibreChat officeHtmlBucket extension precedence and extensionless MIME fallback."""
    basename = name.replace("\\", "/").rsplit("/", 1)[-1]
    extension = basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
    if extension in _OFFICE_EXTENSIONS:
        return _OFFICE_EXTENSIONS[extension]
    if extension:
        return None
    mime = mime_type.split(";", 1)[0].strip().lower()
    if mime == DOCX_MIME:
        return "docx"
    if mime in {"text/csv", "application/csv", "text/comma-separated-values"}:
        return "csv"
    if mime in {XLSX_MIME, ODS_MIME, "application/vnd.ms-excel", "application/msexcel",
                "application/x-ms-excel", "application/x-xls", "application/x-dos_ms_excel"}:
        return "spreadsheet"
    if mime in {PPTX_MIME, POTX_MIME}:
        return "presentation"
    return None


@contextmanager
def _safe_archive(data: bytes):
    """Count actually inflated bytes in chunks, never trusting ZIP header sizes."""
    with ZipFile(io.BytesIO(data)) as archive:
        total = 0
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            if entry.file_size > MAX_ENTRY_BYTES or total + entry.file_size > MAX_TOTAL_BYTES:
                raise UnsafeOfficeArchive("Office archive decompressed size limit exceeded")
            entry_total = 0
            with archive.open(entry) as source:
                while block := source.read(65536):
                    entry_total += len(block)
                    total += len(block)
                    if entry_total > MAX_ENTRY_BYTES or total > MAX_TOTAL_BYTES:
                        raise UnsafeOfficeArchive("Office archive decompressed size limit exceeded")
        yield archive


def _read_xml(archive: ZipFile, path: str) -> ET.Element:
    info = archive.getinfo(path)
    if info.file_size > MAX_ENTRY_BYTES:
        raise UnsafeOfficeArchive("Office XML entry size limit exceeded")
    source = archive.read(path)
    # XML supports UTF-16/UTF-32 and accepts entity declarations in those
    # encodings. Check all byte lanes, not just the UTF-8 byte representation.
    for stride in (1, 2, 4):
        for lane in range(stride):
            probe = source[lane::stride].upper()
            if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
                raise UnsafeOfficeArchive("Office XML must not contain a DTD")
    return ET.fromstring(source)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(node: ET.Element) -> str:
    return "".join(child.text or "" for child in node.iter() if _local(child.tag) in {"t", "v"})


def _docx_text(node: ET.Element) -> str:
    def paragraph(para: ET.Element) -> str:
        fragments = []
        for part in para.iter():
            tag = _local(part.tag)
            if tag == "t":
                fragments.append(part.text or "")
            elif tag == "tab":
                fragments.append("\t")
            elif tag in {"br", "cr"}:
                fragments.append("\n")
        return "".join(fragments)

    if _local(node.tag) == "p":
        return paragraph(node)
    return "\n".join(paragraph(part) for part in node.iter() if _local(part.tag) == "p")


def _escape(value: str) -> str:
    return html.escape(value, quote=True).replace("&#x27;", "&#39;")


_STYLES = """<style>
:root{color-scheme:light dark;--bg:#fff;--fg:#1f2937;--border:#b9bdc5;--shade:#f4f5f7}
@media(prefers-color-scheme:dark){:root{--bg:#191b26;--fg:#e5e7eb;--border:#50576a;--shade:#252937}}
html,body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,Arial,sans-serif}
body{margin:0;padding:16px;overflow-wrap:anywhere}table{border-collapse:collapse;max-width:100%;font-size:13px}
th,td{border:1px solid var(--border);padding:4px 8px;white-space:pre-wrap}
th{background:var(--shade)}.lc-table-scroll{max-width:100%;overflow-x:auto}
.lc-banner{padding:6px 10px;background:var(--shade);border:1px solid var(--border);border-radius:5px}
.lc-sheet-tabs{display:flex;gap:8px;margin-bottom:12px}.lc-sheet-tab-radio{position:absolute;opacity:0;pointer-events:none}
.lc-sheet-panel{display:none}
.lc-pptx-list{list-style:none;padding:0}.lc-pptx-slide{padding:16px;border:1px solid var(--border);margin:0 0 14px}
.lc-pptx-slide-number{font-size:12px;opacity:.7}.lc-docx p{margin:8px 0}
</style>"""


def _document(body: str, css: str = "") -> str:
    content = f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Preview</title>{_STYLES}{css}</head><body>{body}</body></html>'
    if len(content.encode("utf-8")) > OFFICE_HTML_OUTPUT_CAP:
        raise ValueError("Office preview output exceeds 512 KiB")
    return content


def _bounded_rows(rows):
    consumed = 0
    for index, row in enumerate(rows):
        if index >= MAX_ROWS or consumed >= MAX_VISIBLE_CHARS:
            break
        prepared = []
        for value in row[:MAX_COLUMNS]:
            text = str(value or "")
            room = max(0, MAX_VISIBLE_CHARS - consumed)
            text = text[:room]
            consumed += len(text)
            prepared.append(text)
            if consumed >= MAX_VISIBLE_CHARS:
                break
        yield prepared


def _table(rows):
    return '<table><tbody>' + "".join('<tr>' + "".join(f'<td>{_escape(value)}</td>' for value in row)
                                            + '</tr>' for row in _bounded_rows(rows)) + '</tbody></table>'


def _sheets(sheets, *, source_truncated: bool = False):
    if not sheets:
        return _document('<p class="lc-banner">This workbook contains no sheets.</p>')
    css = "".join(f'#lc-sheet-tab-{i}:checked~#lc-sheet-panel-{i}' + '{display:block}'
                  for i in range(len(sheets)))
    radios = "".join(f'<input type="radio" class="lc-sheet-tab-radio" name="lc-sheet" id="lc-sheet-tab-{i}"'
                     + (' checked' if i == 0 else '') + '>' for i in range(len(sheets)))
    tabs = '<nav class="lc-sheet-tabs">' + "".join(
        f'<label for="lc-sheet-tab-{i}">{_escape(name)}</label>' for i, (name, _, _) in enumerate(sheets)
    ) + '</nav>' if len(sheets) > 1 else ''
    panels = ''
    for i, (_, rows, total) in enumerate(sheets):
        visible = list(_bounded_rows(rows))
        clipped = source_truncated or total > len(visible) or len(rows) > len(visible)
        if not clipped:
            for original, rendered in zip(rows, visible, strict=False):
                if len(original) != len(rendered) or any(
                    str(value or "") != shown for value, shown in zip(original, rendered, strict=False)
                ):
                    clipped = True
                    break
        banner = (f'<div class="lc-banner">Showing first {len(visible):,} of {total:,} rows. '
                  'Preview truncated; download the file to see the rest.</div>') if clipped else ''
        panels += f'<section class="lc-sheet-panel" id="lc-sheet-panel-{i}">{banner}' \
                  f'<div class="lc-table-scroll">{_table(visible)}</div></section>'
    return _document(radios + tabs + panels, '<style>' + css + '</style>')


def _csv_html(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    input_limit = MAX_VISIBLE_CHARS * 2
    rows = list(csv.reader(io.StringIO(text[:input_limit])))
    return _sheets([("CSV", rows, max(0, text.count("\n") + bool(text and not text.endswith("\n"))))],
                   source_truncated=len(text) > input_limit)


def _docx_blocks(node: ET.Element):
    for child in node:
        kind = _local(child.tag)
        if kind in {'p', 'tbl'}:
            yield child
        elif kind in {'sdt', 'sdtContent', 'customXml', 'ins'}:
            yield from _docx_blocks(child)


def _docx_html(z: ZipFile) -> str:
    root = _read_xml(z, "word/document.xml")
    body = root.find('.//{*}body')
    if body is None:
        return _document('<article class="lc-docx"></article>')
    lines = []
    consumed = 0
    clipped = False
    for child in _docx_blocks(body):
        if consumed >= MAX_VISIBLE_CHARS:
            clipped = True
            break
        kind = _local(child.tag)
        if kind == "p":
            entire = _docx_text(child)
            remaining = MAX_VISIBLE_CHARS - consumed
            if len(entire) > remaining:
                clipped = True
            value = entire[:remaining]
            consumed += len(value)
            lines.append(f'<p>{_escape(value)}</p>')
        elif kind == "tbl":
            rows = []
            all_rows = child.findall('./{*}tr')
            if len(all_rows) > MAX_ROWS:
                clipped = True
            for tr in all_rows[:MAX_ROWS]:
                cells = [_docx_text(tc) for tc in tr.findall('./{*}tc')]
                if len(cells) > MAX_COLUMNS:
                    clipped = True
                remaining = max(0, MAX_VISIBLE_CHARS - consumed)
                bounded = []
                for cell in cells[:MAX_COLUMNS]:
                    if len(cell) > remaining:
                        clipped = True
                    bounded.append(cell[:remaining])
                    consumed += len(bounded[-1])
                    remaining = max(0, MAX_VISIBLE_CHARS - consumed)
                rows.append(bounded)
                if not remaining:
                    clipped = True
                    break
            lines.append('<div class="lc-table-scroll">' + _table(rows) + '</div>')
    if clipped:
        lines.append('<div class="lc-banner">Preview truncated. Download the file to see the rest.</div>')
    return _document('<article class="lc-docx">' + "".join(lines) + '</article>')


def _xlsx_date_styles(z: ZipFile) -> tuple[set[int], set[int], dict[int, bool]]:
    if 'xl/styles.xml' not in z.namelist():
        return set(), set(), {}
    root = _read_xml(z, 'xl/styles.xml')
    formats = {int(fmt.get('numFmtId')): fmt.get('formatCode', '')
               for fmt in root.findall('./{*}numFmts/{*}numFmt')
               if str(fmt.get('numFmtId', '')).isdigit()}
    styles = root.find('./{*}cellXfs')
    if styles is None:
        return set(), set(), {}
    builtins = set(range(14, 23)) | set(range(27, 37)) | set(range(50, 59))
    result, durations, clocks = set(), set(), {}
    for index, style in enumerate(styles):
        code = int(style.get('numFmtId', '0'))
        fmt = formats.get(code, '')
        # Strip quoted literals, escapes, and bracketed color/locale markers.
        fmt = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', '', fmt).lower()
        if code in {45, 46, 47} or re.search(r'\[(?:h+|m+|s+)\]', formats.get(code, '').lower()):
            durations.add(index)
        elif code in {18, 19, 20, 21} or (
                code in formats and bool(re.search(r'[hs]', fmt))
                and not bool(re.search(r'[yd]', fmt))):
            # A clock-time is a fraction of a day, not a calendar date.
            # Built-ins 18-21 and custom h:mm / h:mm:ss have no epoch.
            clocks[index] = code in {19, 21} or 's' in fmt
        elif code in builtins or (code in formats and bool(re.search(r'[ymdhs]', fmt))):
            result.add(index)
    return result, durations, clocks


def _excel_clock(raw: str, *, seconds: bool = False) -> str:
    value = float(raw)
    if not (0 <= value < 3_000_000):
        return raw
    total = round((value % 1) * 86_400)
    hour, remain = divmod(total % 86_400, 3600)
    minute, second = divmod(remain, 60)
    return f'{hour:02d}:{minute:02d}:{second:02d}' if seconds else f'{hour:02d}:{minute:02d}'


def _excel_duration(raw: str) -> str:
    total = round(abs(float(raw)) * 86400)
    hours, remaining = divmod(total, 3600)
    minutes, seconds = divmod(remaining, 60)
    return f"{'-' if float(raw) < 0 else ''}{hours:02d}:{minutes:02d}:{seconds:02d}"


def _excel_date(raw: str, epoch1904: bool) -> str:
    from datetime import datetime, timedelta

    value = float(raw)
    if not (-100000 < value < 3000000):
        return raw
    if epoch1904:
        base = datetime(1904, 1, 1)
    else:
        base = datetime(1899, 12, 31)
        if value >= 60:
            value -= 1  # Excel 1900 leap-year compatibility bug
    rendered = base + timedelta(days=value)
    return rendered.date().isoformat() if value.is_integer() else rendered.isoformat(sep=' ', timespec='seconds')


def _xlsx_html(z: ZipFile) -> str:
    names = set(z.namelist())
    shared = []
    if 'xl/sharedStrings.xml' in names:
        strings = _read_xml(z, 'xl/sharedStrings.xml')
        shared = [_text(si) for si in strings.findall('./{*}si')]
    workbook = _read_xml(z, 'xl/workbook.xml')
    epoch1904 = (workbook.find('./{*}workbookPr') is not None and
                 workbook.find('./{*}workbookPr').get('date1904') in {'1', 'true'})
    date_styles, duration_styles, clock_styles = _xlsx_date_styles(z)
    rels = {}
    if 'xl/_rels/workbook.xml.rels' in names:
        for rel in _read_xml(z, 'xl/_rels/workbook.xml.rels'):
            identifier = rel.get('Id')
            target = rel.get('Target', '').lstrip('/')
            if identifier and '..' not in PurePosixPath(target).parts and ':' not in target:
                rels[identifier] = target if target.startswith('xl/') else 'xl/' + target
    sheets = []
    for index, sheet in enumerate(workbook.findall('./{*}sheets/{*}sheet')):
        name = sheet.get('name', f'Sheet{index+1}')
        rel_id = (sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                  or sheet.get('{http://purl.oclc.org/ooxml/officeDocument/relationships}id'))
        location = rels.get(rel_id, f'xl/worksheets/sheet{index+1}.xml')
        if location not in names:
            continue
        root = _read_xml(z, location)
        sheet_data = root.find('./{*}sheetData')
        rows = []
        total = 0
        if sheet_data is not None:
            for row in sheet_data.findall('./{*}row'):
                total += 1
                if len(rows) >= MAX_ROWS:
                    continue
                cells = {}
                for cell in row.findall('./{*}c'):
                    address = cell.get('r', '')
                    match = re.match(r'^([A-Z]+)', address)
                    column = 0
                    if match:
                        for char in match[1]:
                            column = column * 26 + ord(char) - 64
                        column -= 1
                    else:
                        column = len(cells)
                    if column >= MAX_COLUMNS:
                        continue
                    kind = cell.get('t', '')
                    if kind == 'inlineStr':
                        value = _text(cell.find('./{*}is')) if cell.find('./{*}is') is not None else ''
                    else:
                        raw = cell.findtext('./{*}v', default='')
                        if kind == 's':
                            try:
                                value = shared[int(raw)]
                            except (IndexError, ValueError):
                                value = ''
                        else:
                            value = raw
                            style_index = cell.get('s', '0')
                            if kind in {'', 'n'} and style_index.isdigit() and raw:
                                try:
                                    if int(style_index) in duration_styles:
                                        value = _excel_duration(raw)
                                    elif int(style_index) in clock_styles:
                                        value = _excel_clock(raw, seconds=clock_styles[int(style_index)])
                                    elif int(style_index) in date_styles:
                                        value = _excel_date(raw, epoch1904)
                                except (ValueError, OverflowError):
                                    value = raw
                    cells[column] = value
                if cells:
                    rows.append([cells.get(i, '') for i in range(min(MAX_COLUMNS, max(cells) + 1))])
                else:
                    rows.append([])
        sheets.append((name, rows, total))
    return _sheets(sheets)


def _xls_html(data: bytes) -> str:
    """SheetJS legacy-BIFF fallback with a small pure-Python XLS reader."""
    from struct import error as StructError

    try:
        import xlrd
        from xlrd.compdoc import CompDocError
        from xlrd.xldate import xldate_as_datetime
    except ImportError as exc:
        # Rendering is optional. The publisher records a failed preview while
        # keeping the original XLS attachment available for download.
        raise ValueError('Legacy XLS preview requires xlrd') from exc

    try:
        book = xlrd.open_workbook(file_contents=data, on_demand=True)
    except (xlrd.XLRDError, CompDocError, StructError, IndexError) as exc:
        # Corrupt OLE/BIFF is untrusted input. Normalize parser-specific
        # failures into the producer's optional-preview fallback so that
        # the original binary remains downloadable.
        raise ValueError("Invalid legacy XLS workbook") from exc
    try:
        sheets = []
        for sheet in book.sheets():
            rows = []
            for i in range(min(sheet.nrows, MAX_ROWS)):
                values = []
                for j in range(min(sheet.ncols, MAX_COLUMNS)):
                    item = sheet.cell_value(i, j)
                    if sheet.cell_type(i, j) == xlrd.XL_CELL_DATE:
                        try:
                            date = xldate_as_datetime(item, book.datemode)
                            values.append(date.date().isoformat() if not (date.hour or date.minute or date.second)
                                          else date.isoformat(sep=' ', timespec='seconds'))
                        except (TypeError, ValueError, OverflowError, xlrd.XLDateError):
                            values.append(str(item))
                    else:
                        values.append(str(int(item)) if isinstance(item, float) and item.is_integer()
                                      else str(item) if item is not None else '')
                rows.append(values)
            sheets.append((sheet.name, rows, sheet.nrows))
        return _sheets(sheets)
    finally:
        book.release_resources()


def _ods_html(z: ZipFile) -> str:
    root = _read_xml(z, 'content.xml')
    sheets = []
    for index, table in enumerate(node for node in root.iter() if _local(node.tag) == 'table'):
        name = next((value for key, value in table.attrib.items() if _local(key) == 'name'), f'Sheet{index+1}')
        rows = []
        total = 0
        # ODS row groups, headers and footer groups all contain actual
        # table-row children. Iterate those in document order, rather than
        # pretending table-header-rows itself contains cells.
        for row in table.iter():
            if _local(row.tag) != 'table-row':
                continue
            count = int(next((v for k, v in row.attrib.items() if _local(k) == 'number-rows-repeated'), '1'))
            count = min(max(1, count), MAX_ROWS+1)
            cells = []
            for cell in row:
                if _local(cell.tag) not in {'table-cell', 'covered-table-cell'}:
                    continue
                # itertext includes nested formatting and each element's
                # following tail, retaining the original paragraph order.
                text = ' '.join(''.join(p.itertext()) for p in cell if _local(p.tag) == 'p').strip()
                if not text:
                    text = next((v for k, v in cell.attrib.items() if _local(k) in {'value', 'date-value', 'boolean-value'}), '')
                repeat = int(next((v for k, v in cell.attrib.items() if _local(k) == 'number-columns-repeated'), '1'))
                cells.extend([text] * min(max(1, repeat), MAX_COLUMNS - len(cells)))
                if len(cells) >= MAX_COLUMNS:
                    break
            total += count
            for _ in range(min(count, max(0, MAX_ROWS-len(rows)))):
                rows.append(cells)
        sheets.append((name, rows, total))
    return _sheets(sheets)


def _ordered_presentation_slides(z: ZipFile) -> list[str]:
    """OOXML presentation order is an sldId/rId list, not ZIP filename order."""
    available = {
        path for path in z.namelist()
        if re.fullmatch(r'ppt/slides/slide[0-9]+\.xml', path)
    }
    manifest = 'ppt/presentation.xml'
    relations = 'ppt/_rels/presentation.xml.rels'
    if manifest in z.namelist() and relations in z.namelist():
        rels = {}
        for rel in _read_xml(z, relations):
            if (rel.get('TargetMode') or '').lower() == 'external':
                continue
            if not rel.get('Type', '').endswith('/slide'):
                continue
            target = rel.get('Target', '')
            if not target or ':' in target or '..' in PurePosixPath(target).parts:
                continue
            resolved = target.lstrip('/') if target.startswith('/') else 'ppt/' + target
            if resolved in available:
                rels[rel.get('Id')] = resolved
        root = _read_xml(z, manifest)
        slide_list = root.find('.//{*}sldIdLst')
        if slide_list is not None:
            ordered = []
            for slide in slide_list:
                path = rels.get(slide.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'))
                if path is not None:
                    ordered.append(path)
            # Do not expose orphaned slides omitted from the live presentation.
            if ordered:
                return ordered
    # Legacy/malformed fixtures without manifests retain deterministic fallback.
    return sorted(available, key=lambda item: int(re.search(r'slide([0-9]+)', item)[1]))


def _presentation_html(z: ZipFile) -> str:
    slides = _ordered_presentation_slides(z)
    body = []
    remaining = MAX_VISIBLE_CHARS
    truncated = False
    for number, path in enumerate(slides[:MAX_SLIDES], start=1):
        root = _read_xml(z, path)
        paragraphs = []
        for para in root.iter():
            if _local(para.tag) != 'p':
                continue
            content = ''.join((node.text or '') for node in para.iter() if _local(node.tag) == 't').strip()
            if not content:
                continue
            if remaining <= 0:
                truncated = True
                break
            text = content[:remaining]
            paragraphs.append(text)
            remaining -= len(text)
            if len(text) < len(content):
                truncated = True
                break
        title = f'<h2 class="lc-pptx-slide-title">{_escape(paragraphs[0])}</h2>' if paragraphs else ''
        bullets = '<ul class="lc-pptx-slide-body">' + ''.join(f'<li>{_escape(line)}</li>' for line in paragraphs[1:]) + '</ul>' if len(paragraphs) > 1 else ''
        if not title:
            bullets = '<p class="lc-pptx-slide-empty">(empty slide)</p>'
        body.append(f'<li class="lc-pptx-slide"><span class="lc-pptx-slide-number">Slide {number}</span>{title}{bullets}</li>')
        if truncated:
            break
    if truncated or len(slides) > MAX_SLIDES:
        body.append('<li class="lc-banner">Preview truncated. Download the file to see the rest.</li>')
    return _document('<ol class="lc-pptx-list">' + ''.join(body) + '</ol>' if body else
                     '<p class="lc-banner">This presentation contains no readable slides.</p>')


def buffer_to_office_html(data: bytes, name: str, mime_type: str) -> str | None:
    """Render recognized tool-output Office buffers as escaped static HTML.

    Legacy BIFF XLS is parsed with the small pure-Python `xlrd` library,
    while ZIP-backed OOXML and ODS formats use the bounded stdlib parser.
    The caller always persists the original bytes independent of rendering.
    """
    bucket = office_html_bucket(name, mime_type)
    if bucket is None:
        return None
    if bucket == 'csv':
        return _csv_html(data)
    if bucket == 'spreadsheet' and data.startswith(b'\xd0\xcf\x11\xe0'):
        return _xls_html(data)
    if not data.startswith(b'PK'):
        raise ValueError('Unsupported non-ZIP Office input')
    try:
        with _safe_archive(data) as z:
            if bucket == 'docx':
                return _docx_html(z)
            if bucket == 'spreadsheet':
                return _ods_html(z) if 'content.xml' in z.namelist() else _xlsx_html(z)
            return _presentation_html(z)
    except (BadZipFile, zlib.error, EOFError) as error:
        raise ValueError('Malformed Office archive') from error
    except (NotImplementedError, RuntimeError) as error:
        # Unsupported ZIP compression/encryption is an optional preview
        # failure; the authorized native file_write retains its bytes.
        raise ValueError('Unsupported Office ZIP feature') from error


class _PreviouslyPublished(Exception):
    def __init__(self, value: dict):
        self.value = value


async def publish_office_tool_output(owner: str, run_id: str, tool_call_id: str,
                                     filename: str, mime_type: str, data: bytes,
                                     *, database, state_dir) -> dict:
    """Publish trusted tool-generated Office bytes and original attachment SSE atomically.

    Only the controller may call this with its actual run/tool-call identity;
    no request JSON or model-supplied file path is accepted. A successful
    publication atomically inserts the owner-bound file metadata, the
    conversation link and its original LibreChat ``attachment`` event. On
    crashed/replayed identical callbacks the first committed file wins.
    """
    import asyncio
    import hashlib
    import json

    from .attachments import file_record, publish_attachment

    if not isinstance(data, bytes) or not data:
        raise ValueError('Tool output must contain non-empty original file bytes')
    if not run_id or not tool_call_id or len(tool_call_id) > 256:
        raise ValueError('A trusted run and tool-call identity are required')
    # Fast authorization before parsing or allocating a file. The callback's
    # INSERT transaction repeats it, closing the concurrent-finish window.
    with database.connect() as db:
        run = db.execute('SELECT r.status FROM runs r JOIN conversations c '
                         'ON c.id=r.conversation_id WHERE r.id=? AND c.owner=?',
                         (run_id, owner)).fetchone()
    if run is None or run['status'] != 'running':
        raise PermissionError('The owner run is no longer active')
    bucket = office_html_bucket(filename, mime_type)
    if bucket is None:
        raise ValueError('Not an Office preview artifact')
    # Attachment storage strips directories; deduplication must use the same
    # canonical filename as the committed attachment event.
    filename = PurePosixPath(filename.replace("\\", "/")).name
    digest = hashlib.sha256(data).hexdigest()
    try:
        preview = await asyncio.to_thread(buffer_to_office_html, data, filename, mime_type)
        metadata = {'status': 'ready', 'text': preview, 'textFormat': 'html',
                    'trustedOfficeRenderer': 'escaped-office-v1', 'context': 'tool_output'}
    except (ValueError, ET.ParseError, OSError, KeyError, OverflowError, csv.Error):
        metadata = {'status': 'failed', 'previewError': 'unsupported', 'context': 'tool_output'}
    metadata['sourceDigest'] = digest
    metadata['toolCallId'] = tool_call_id

    async def chunks():
        yield data

    def bind(db, file_id):
        row = db.execute(
            'SELECT r.conversation_id,r.status,r.state FROM runs r '
            'JOIN conversations c ON c.id=r.conversation_id '
            'WHERE r.id=? AND c.owner=?', (run_id, owner),
        ).fetchone()
        if row is None or row['status'] != 'running':
            raise PermissionError('The owner run is no longer active')
        previous = db.execute(
            'SELECT e.data FROM generation_events e WHERE e.run_id=? '
            "AND json_extract(e.data,'$.event')='attachment' "
            "AND json_extract(e.data,'$.data.toolCallId')=? "
            "AND json_extract(e.data,'$.data.filename')=? "
            "AND json_extract(e.data,'$.data.sourceDigest')=? LIMIT 1",
            (run_id, tool_call_id, filename, digest),
        ).fetchone()
        if previous is not None:
            prior = json.loads(previous['data'])['data']
            raise _PreviouslyPublished(prior)
        db.execute('UPDATE attachments SET conversation_id=? WHERE id=? AND owner=?',
                   (row['conversation_id'], file_id, owner))
        attachment_row = db.execute('SELECT * FROM attachments WHERE id=? AND owner=?',
                                    (file_id, owner)).fetchone()
        state = json.loads(row['state'])
        message_id = state.get('responseMessageId')
        if not isinstance(message_id, str) or not message_id:
            raise ValueError('Missing trusted response message identity')
        db.execute(
            'INSERT INTO tool_attachment_links(run_id,response_message_id,tool_call_id,file_id) '
            'VALUES(?,?,?,?)', (run_id, message_id, tool_call_id, file_id),
        )
        descriptor = {**file_record(attachment_row), 'messageId': message_id,
                      'toolCallId': tool_call_id, 'conversationId': row['conversation_id']}
        db.execute('INSERT INTO generation_events(run_id,data) VALUES(?,?)',
                   (run_id, json.dumps({'event': 'attachment', 'data': descriptor},
                                       ensure_ascii=False, separators=(',', ':'))))

    try:
        artifact = await publish_attachment(owner, filename, mime_type, chunks(), state_dir,
                                            expected_size=len(data), metadata=metadata, bind=bind)
    except _PreviouslyPublished as prior:
        return prior.value
    with database.connect() as db:
        row = db.execute('SELECT * FROM attachments WHERE id=? AND owner=?',
                         (artifact['file_id'], owner)).fetchone()
    return {**file_record(row), 'toolCallId': tool_call_id}


async def publish_native_file_write(owner: str, generation, tool_call, output: str,
                                    *, database, state_dir) -> dict | None:
    """Bridge an *already executed* authorized local native file_write to Artifacts.

    The native file-write tool returns the hash, size and canonical filename of
    bytes it actually wrote. We only publish if those trusted, native values
    match the bytes submitted to the authorized tool. Never use a model-authored
    path or a raw tool-result claim as independent permission to read files.
    The prior native authorization cannot be bypassed by this callback.
    """
    import base64
    import binascii
    import hashlib
    import json

    if tool_call.name != 'file_write' or not isinstance(tool_call.arguments, dict):
        return None
    args = tool_call.arguments
    machine = args.get('machine')
    if machine is not None and (not isinstance(machine, str) or machine not in {'', 'local'}):
        return None
    try:
        response = json.loads(output)
    except (TypeError, ValueError):
        return None
    if not isinstance(response, dict) or response.get('ok') is not True:
        return None
    written = response.get('data')
    if not isinstance(written, dict):
        return None
    filename, expected_hash, expected_size = written.get('path'), written.get('sha256'), written.get('bytes')
    if not isinstance(filename, str) or not filename or not isinstance(expected_hash, str) or type(expected_size) is not int:
        return None
    if office_html_bucket(filename, 'application/octet-stream') is None:
        return None
    content = args.get('content')
    if not isinstance(content, str):
        return None
    try:
        if args.get('encoding') == 'base64':
            original = base64.b64decode(content, validate=True)
        elif args.get('encoding') is None or args.get('encoding') == 'utf-8':
            original = content.encode('utf-8')
        else:
            return None
    except (UnicodeError, ValueError, binascii.Error):
        return None
    if (len(original) != expected_size or not original or
        hashlib.sha256(original).hexdigest() != expected_hash):
        return None
    from .attachments import MAX_ATTACHMENT_BYTES

    if len(original) > MAX_ATTACHMENT_BYTES:
        return None
    return await publish_office_tool_output(
        owner, generation.run_id, tool_call.call_id, filename,
        'application/octet-stream', original, database=database, state_dir=state_dir,
    )
