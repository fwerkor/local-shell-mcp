"""Pinned LibreChat Office fixture vector, ZIP bomb and real SQLite tool replay tests."""
from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from local_shell_mcp.webui.office_preview import (
    DOCX_MIME,
    MAX_ENTRY_BYTES,
    UnsafeOfficeArchive,
    buffer_to_office_html,
    office_html_bucket,
)

FIXTURES = Path(__file__).parent / "fixtures/librechat/office"


@pytest.mark.parametrize(('name', 'markers'), [
    ('sample.docx', ['This is a sample DOCX file.', 'lc-docx']),
    ('sample.xlsx', ['Data', 'On', 'Second', 'lc-sheet-panel-1']),
    ('sample.ods', ['Data', 'On', 'Second', 'lc-sheet-panel-1']),
    ('sample.xls', ['Data', 'on', 'first', 'sheet']),
    ('sample.pptx', ['LibreChat conversion fixture', 'Slide 1', 'lc-pptx-list']),
    ('empty.docx', ['lc-docx']),
])
def test_pinned_librechat_office_binary_samples(name, markers):
    rendered = buffer_to_office_html((FIXTURES / name).read_bytes(), name, 'application/octet-stream')
    assert rendered.startswith('<!DOCTYPE html>')
    assert '<script' not in rendered.lower()
    assert '<iframe' not in rendered.lower()
    assert len(rendered.encode('utf8')) <= 512 * 1024
    for marker in markers:
        assert marker in rendered


@pytest.mark.parametrize(('name', 'mime', 'bucket'), [
    ('report.docx', 'text/csv', 'docx'),
    ('deck.pptx', 'text/csv', 'presentation'),
    ('report.txt', DOCX_MIME, None),
    ('weird.bin', DOCX_MIME, None),
    ('noext', DOCX_MIME + '; charset=utf-8', 'docx'),
    ('report.CSV', 'application/octet-stream', 'csv'),
    ('noext', 'text/comma-separated-values', 'csv'),
    ('noext', 'application/x-ms-excel', 'spreadsheet'),
    ('noext', 'application/octet-stream', None),
])
def test_original_office_bucket_precedence(name, mime, bucket):
    assert office_html_bucket(name, mime) == bucket


def _archive_xml(path, payload):
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr(path, payload)
    return output.getvalue()


def test_office_preview_escapes_untrusted_content_and_avoids_script_or_url():
    malicious = 'Hello <script>alert(1)</script> & <img src=x onerror=alert(2)>'
    docx = _archive_xml('word/document.xml',
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        '<w:p><w:r><w:t>' + malicious.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        + '</w:t></w:r></w:p></w:body></w:document>')
    rendered = buffer_to_office_html(docx, 'x.docx', DOCX_MIME)
    assert '&lt;script&gt;' in rendered and '&lt;img src=x onerror=' in rendered
    assert '<script' not in rendered and '<img' not in rendered
    csv_html = buffer_to_office_html(b'a,<script>alert(1)</script>\n', 'data.csv', 'text/csv')
    assert '&lt;script&gt;' in csv_html and '<script' not in csv_html


def test_office_rejects_xml_entities_and_inflation_and_unknown_binary():
    unsafe = _archive_xml('word/document.xml', '<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><foo/>')
    with pytest.raises(UnsafeOfficeArchive, match='DTD'):
        buffer_to_office_html(unsafe, 'x.docx', DOCX_MIME)
    bomb = _archive_xml('word/document.xml', b'a' * (MAX_ENTRY_BYTES+1024))
    with pytest.raises(UnsafeOfficeArchive, match='decompressed'):
        buffer_to_office_html(bomb, 'x.docx', DOCX_MIME)
    with pytest.raises(ValueError, match='non-ZIP'):
        buffer_to_office_html(b'not a real legacy XLS', 'sample.xls', 'application/vnd.ms-excel')
    assert buffer_to_office_html(b'arbitrary', 'report.txt', DOCX_MIME) is None


def test_office_csv_large_preview_is_truncated_with_banner():
    result = buffer_to_office_html(b'name,value\n' + b'example,1\n'*5100, 'report.csv', 'text/csv')
    assert 'Showing first 5,000 of 5,101 rows.' in result
    assert result.count('<tr>') <= 5000




def _synthetic_xlsx(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, source in entries.items():
            archive.writestr(name, source)
    return output.getvalue()


def test_office_empty_tables_missing_docx_body_and_slides():
    from local_shell_mcp.webui.office_preview import _sheets

    assert 'no sheets' in _sheets([])
    docx = _archive_xml('word/document.xml', '<w:document xmlns:w="urn:docx"/>')
    assert '<article class="lc-docx"></article>' in buffer_to_office_html(docx, 'test.docx', DOCX_MIME)
    slides = _archive_xml('ppt/theme/theme1.xml', '<theme/>')
    assert 'no readable slides' in buffer_to_office_html(slides, 'empty.pptx', 'application/octet-stream')


def test_office_html_cap_and_row_char_budget(monkeypatch):
    from local_shell_mcp.webui import office_preview as preview

    with pytest.raises(ValueError, match='512 KiB'):
        preview._document('X' * preview.OFFICE_HTML_OUTPUT_CAP)
    rows = list(preview._bounded_rows([['A'*preview.MAX_VISIBLE_CHARS, 'after'], ['ignored']]))
    assert rows == [['A'*preview.MAX_VISIBLE_CHARS]]
    monkeypatch.setattr(preview, 'MAX_VISIBLE_CHARS', 3)
    assert list(preview._bounded_rows([['xy', 'zzz'], ['ignored']])) == [['xy', 'z']]


def test_office_docx_table_and_truncation_banner():
    text = '<w:p><w:r><w:t>' + 'A'*180000 + '</w:t></w:r></w:p>'
    rows = '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    docx = _archive_xml('word/document.xml',
        '<w:document xmlns:w="urn:docx"><w:body>' + rows + text + '<w:p/></w:body></w:document>')
    result = buffer_to_office_html(docx, 'table.docx', DOCX_MIME)
    assert '<td>table cell</td>' in result
    assert 'Preview truncated' in result


def test_office_synthetic_xlsx_inline_unindexed_numeric_missing_relations():
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    workbook = f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' \
               '<sheet name="test" r:id="rId1"/>' \
               '<sheet name="missing" r:id="rId2"/></sheets></workbook>'
    sheet = (f'<worksheet xmlns="{ns}"><sheetData>'
             '<row><c t="inlineStr"><is><t>INLINE</t></is></c>'
             '<c r="ZZ5000"><v>ignored</v></c>'
             '<c r="B2" t="s"><v>99</v></c>'
             '<c r="C2"><v>42</v></c></row><row/>'
             '</sheetData></worksheet>')
    archive = _synthetic_xlsx({'xl/workbook.xml': workbook, 'xl/worksheets/sheet1.xml': sheet,
                               'xl/sharedStrings.xml': f'<sst xmlns="{ns}"><si><t>value</t></si></sst>'})
    result = buffer_to_office_html(archive, 'sheet.xlsx', 'application/octet-stream')
    assert 'INLINE' in result and '<td>42</td>' in result
    assert '<td></td>' in result
    assert 'ignored' not in result
    assert 'missing' not in result


def test_office_synthetic_xlsx_malicious_relation_and_missing_rows():
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    workbook = f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' \
               '<sheets><sheet name="Odd" r:id="r1"/></sheets></workbook>'
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="r1" Target="../private.xml"/></Relationships>')
    archive = _synthetic_xlsx({'xl/workbook.xml': workbook,
                               'xl/_rels/workbook.xml.rels': rels,
                               'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{ns}"/>'})
    rendered = buffer_to_office_html(archive, 'safe.xlsx', 'application/octet-stream')
    assert 'Odd' not in rendered  # Single-sheet label omitted by original UI.
    assert '<table' in rendered


def test_office_synthetic_ods_repeated_rows_and_value_fallback():
    xml = ('<office:document-content '
           'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
           '<office:body><office:spreadsheet><table:table table:name="Money">'
           '<table:table-row table:number-rows-repeated="3">'
           '<table:table-cell office:value="42" table:number-columns-repeated="2" />'
           '<table:covered-table-cell/>'
           '<table:cell-hidden/>'
           '</table:table-row></table:table></office:spreadsheet></office:body></office:document-content>')
    data = _archive_xml('content.xml', xml)
    rendered = buffer_to_office_html(data, 'data.ods', 'application/octet-stream')
    assert rendered.count('<tr>') == 3
    assert rendered.count('<td>42</td>') == 6


def test_office_synthetic_pptx_multislide_bullets_and_empty():
    slides = _synthetic_xlsx({
        'ppt/slides/slide2.xml': '<p:sld xmlns:p="urn:p" xmlns:a="urn:a">'
                                 '<a:p><a:r><a:t>Second</a:t></a:r></a:p>'
                                 '<a:p><a:r><a:t>Bullet 1</a:t></a:r></a:p>'
                                 '<a:p/></p:sld>',
        'ppt/slides/slide1.xml': '<p:sld xmlns:p="urn:p"><p:spTree/></p:sld>',
        'ppt/media/image.png': 'ignored',
    })
    result = buffer_to_office_html(slides, 'deck.pptx', 'application/octet-stream')
    assert result.find('Slide 1') < result.find('Slide 2')
    assert '(empty slide)' in result
    assert '<li>Bullet 1</li>' in result
    assert 'image.png' not in result


def test_office_corrupt_ole_xls_is_invalid_preview_not_unhandled_parser_exception():
    raw = (FIXTURES / 'sample.xls').read_bytes()
    for malformed in (raw[:64], raw[:8] + b'\0' * 4096):
        with pytest.raises(ValueError, match='Invalid legacy XLS workbook'):
            buffer_to_office_html(malformed, 'broken.xls', 'application/vnd.ms-excel')


def test_office_invalid_zip_and_reject_entry_over_max(monkeypatch):
    from local_shell_mcp.webui import office_preview as preview

    with pytest.raises(ValueError, match='Malformed Office'):
        preview.buffer_to_office_html(b'PK-broken', 'report.docx', DOCX_MIME)
    payload = _archive_xml('word/document.xml', '<doc/>')
    monkeypatch.setattr(preview, 'MAX_ENTRY_BYTES', 2)
    with pytest.raises(UnsafeOfficeArchive, match='size limit'):
        preview.buffer_to_office_html(payload, 'report.docx', DOCX_MIME)
