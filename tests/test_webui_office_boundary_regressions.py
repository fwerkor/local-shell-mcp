"""Archive size, XML and spreadsheet-date boundaries for native Office previews."""
from __future__ import annotations

import io
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from local_shell_mcp.webui import office_preview as office


def _archive(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with ZipFile(out, 'w', compression=ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16le', 'utf-32le'])
def test_office_xml_rejects_doctype_across_encoded_byte_lanes(encoding):
    source = '<!DOCTYPE doc [<!ENTITY secret SYSTEM "file:///etc/passwd">]><doc>&secret;</doc>'
    raw = _archive({'document.xml': source.encode(encoding)})
    with office._safe_archive(raw) as z, pytest.raises(office.UnsafeOfficeArchive, match='DTD'):
        office._read_xml(z, 'document.xml')


def test_office_archive_enforces_entry_and_total_uncompressed_byte_limits(monkeypatch):
    data = _archive({'first.xml': b'a' * 20, 'second.xml': b'b' * 20})
    monkeypatch.setattr(office, 'MAX_ENTRY_BYTES', 16)
    with pytest.raises(office.UnsafeOfficeArchive, match='size limit'), office._safe_archive(data):
        pass
    monkeypatch.setattr(office, 'MAX_ENTRY_BYTES', 25)
    monkeypatch.setattr(office, 'MAX_TOTAL_BYTES', 30)
    with pytest.raises(office.UnsafeOfficeArchive, match='size limit'), office._safe_archive(data):
        pass


def test_excel_clock_and_calendar_reject_out_of_range_serials_and_keep_1900_epoch():
    assert office._excel_clock('3000000') == '3000000'
    assert office._excel_date('-100000', False) == '-100000'
    assert office._excel_date('3000000', True) == '3000000'
    assert office._excel_date('59', False) == '1900-02-28'
    assert office._excel_date('61', False) == '1900-03-01'
    assert office._excel_date('0', True) == '1904-01-01'
    assert office._excel_date('61.5', False) == '1900-03-01 12:00:00'


def test_xlsx_styles_without_cell_formats_are_not_dates():
    style = b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="mm/dd/yyyy"/></numFmts></styleSheet>'
    with office._safe_archive(_archive({'xl/styles.xml': style})) as z:
        assert office._xlsx_date_styles(z) == (set(), set(), {})
    with office._safe_archive(_archive({'other.txt': b'ok'})) as z:
        assert office._xlsx_date_styles(z) == (set(), set(), {})


def test_docx_nested_content_and_large_table_are_bounded(monkeypatch):
    from xml.etree import ElementTree as ET

    xml = (b'<w:document xmlns:w="urn:word"><w:body>'
           b'<w:sdt><w:sdtContent><w:p><w:r><w:t>Intro</w:t></w:r></w:p></w:sdtContent></w:sdt>'
           b'<w:tbl><w:tr><w:tc><w:p><w:r><w:t>long entry</w:t></w:r></w:p></w:tc>'
           b'<w:tc><w:p><w:r><w:t>second</w:t></w:r></w:p></w:tc></w:tr>'
           b'<w:tr><w:tc><w:p><w:r><w:t>ignored</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           b'</w:body></w:document>')
    monkeypatch.setattr(office, 'MAX_ROWS', 1)
    monkeypatch.setattr(office, 'MAX_COLUMNS', 1)
    monkeypatch.setattr(office, 'MAX_VISIBLE_CHARS', 12)
    with office._safe_archive(_archive({'word/document.xml': xml})) as z:
        preview = office._docx_html(z)
    assert 'Intro' in preview and 'long en' in preview
    assert 'second' not in preview and 'ignored' not in preview
    assert 'Preview truncated' in preview
    # Missing body is a legitimate but empty Office document.
    with office._safe_archive(_archive({'word/document.xml': b'<w:document xmlns:w="urn:word"/>'})) as z:
        assert 'lc-docx' in office._docx_html(z)
    assert list(office._docx_blocks(ET.fromstring('<root><other/></root>'))) == []


def test_docx_caps_long_paragraph_without_consuming_subsequent_blocks(monkeypatch):
    xml = (b'<document><body><p><r><t>abcdef</t></r></p>'
           b'<p><r><t>must not appear</t></r></p></body></document>')
    monkeypatch.setattr(office, 'MAX_VISIBLE_CHARS', 3)
    with office._safe_archive(_archive({'word/document.xml': xml})) as z:
        html = office._docx_html(z)
    assert 'abc' in html and 'must not appear' not in html and 'Preview truncated' in html


def test_xls_date_conversion_failure_preserves_original_cell(monkeypatch):
    import xlrd
    from xlrd import xldate

    class Sheet:
        name = 'Malformed dates'
        nrows, ncols = 1, 3

        def cell_value(self, _row, column):
            return (50000.0, 12.0, None)[column]

        def cell_type(self, _row, column):
            return xlrd.XL_CELL_DATE if column < 2 else xlrd.XL_CELL_EMPTY

    class Book:
        datemode = 0
        closed = False

        def sheets(self):
            return [Sheet()]

        def release_resources(self):
            self.closed = True

    book = Book()
    monkeypatch.setattr(xlrd, 'open_workbook', lambda **_: book)
    original = xldate.xldate_as_datetime
    monkeypatch.setattr(xldate, 'xldate_as_datetime', lambda value, mode: (
        (_ for _ in ()).throw(xlrd.XLDateError('invalid')) if value == 12.0
        else original(value, mode)))
    # The local import is bound at function execution; an invalid date
    # must not prevent producing a safe preview or closing the BIFF handle.
    html = office._xls_html(b'original-biff')
    assert '12.0' in html and '2036-11-21' in html and book.closed
    monkeypatch.setattr(xlrd, 'open_workbook', lambda **_: (_ for _ in ()).throw(xlrd.XLRDError('corrupt')))
    with pytest.raises(ValueError, match='Invalid legacy XLS'):
        office._xls_html(b'corrupt')


def test_xlsx_shared_strings_out_of_range_numeric_styles_and_row_limit(monkeypatch):
    workbook = (b'<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                b'<workbookPr date1904="1"/><sheets><sheet name="Bounded workbook" r:id="rId1"/></sheets></workbook>')
    styles = (b'<styleSheet><cellXfs count="4"><xf numFmtId="14"/>'
              b'<xf numFmtId="20"/><xf numFmtId="46"/><xf numFmtId="0"/>'
              b'</cellXfs></styleSheet>')
    sheet = (b'<worksheet><sheetData><row r="1">'
             b'<c r="A1" t="s"><v>999</v></c>'
             b'<c r="B1" s="0"><v>0</v></c>'
             b'<c r="C1" s="1"><v>0.5</v></c>'
             b'<c r="D1" s="2"><v>1.25</v></c>'
             b'<c r="E1" s="3"><v>original</v></c>'
             b'</row><row r="2"><c r="A2" t="inlineStr"><is><t>hidden</t></is></c></row>'
             b'</sheetData></worksheet>')
    monkeypatch.setattr(office, 'MAX_ROWS', 1)
    with office._safe_archive(_archive({
        'xl/workbook.xml': workbook,
        'xl/styles.xml': styles,
        'xl/sharedStrings.xml': b'<sst><si><t>only one string</t></si></sst>',
        'xl/worksheets/sheet1.xml': sheet,
    })) as z:
        html = office._xlsx_html(z)
    assert '1904-01-01' in html and '12:00' in html and '30:00' in html
    assert 'hidden' not in html and 'Preview truncated' in html


def test_ods_repeated_rows_and_cells_do_not_expand_unboundedly(monkeypatch):
    xml = (b'<office:document-content xmlns:office="urn:o" xmlns:table="urn:t" '
           b'xmlns:text="urn:p"><office:body><office:spreadsheet>'
           b'<table:table table:name="Bounded"><table:table-header-rows>'
           b'<table:table-row table:number-rows-repeated="12">'
           b'<table:table-cell table:number-columns-repeated="15" office:value="42"/>'
           b'</table:table-row></table:table-header-rows>'
           b'</table:table></office:spreadsheet></office:body></office:document-content>')
    monkeypatch.setattr(office, 'MAX_ROWS', 2)
    monkeypatch.setattr(office, 'MAX_COLUMNS', 3)
    with office._safe_archive(_archive({'content.xml': xml})) as z:
        html = office._ods_html(z)
    assert '<td>42</td>' in html and html.count('<td>42</td>') == 6
    assert 'first 2 of 3 rows' in html or 'Preview truncated' in html


def test_pptx_manifest_rejects_external_and_traversal_relationships():
    presentation = (b'<p:presentation xmlns:p="urn:p" '
                    b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    b'<p:sldIdLst><p:sldId r:id="r-good"/><p:sldId r:id="r-external"/>'
                    b'<p:sldId r:id="r-parent"/></p:sldIdLst></p:presentation>')
    relationships = (b'<Relationships>'
                     b'<Relationship Id="r-external" TargetMode="External" Type="urn:schemas/slide" '
                     b'Target="https://attacker.invalid/slide"/>'
                     b'<Relationship Id="r-parent" Type="urn:schemas/slide" Target="../evil.xml"/>'
                     b'<Relationship Id="r-not-slide" Type="urn:other" Target="slides/slide2.xml"/>'
                     b'<Relationship Id="r-good" Type="urn:schemas/slide" Target="slides/slide2.xml"/>'
                     b'</Relationships>')
    files = {'ppt/presentation.xml': presentation,
             'ppt/_rels/presentation.xml.rels': relationships,
             'ppt/slides/slide1.xml': b'<slide/>',
             'ppt/slides/slide2.xml': b'<slide><p><t>Safe slide</t></p></slide>'}
    with office._safe_archive(_archive(files)) as z:
        assert office._ordered_presentation_slides(z) == ['ppt/slides/slide2.xml']
        html = office._presentation_html(z)
    assert 'Safe slide' in html and 'attacker.invalid' not in html


def test_pptx_fallback_keeps_numeric_order_and_bounds_text(monkeypatch):
    files = {
        'ppt/slides/slide10.xml': b'<slide><p><t>Later</t></p></slide>',
        'ppt/slides/slide2.xml': b'<slide><p><t>First paragraph is long</t></p><p><t>hidden</t></p></slide>',
        'ppt/rogue.xml': b'<slide><p><t>rogue</t></p></slide>',
    }
    monkeypatch.setattr(office, 'MAX_VISIBLE_CHARS', 6)
    with office._safe_archive(_archive(files)) as z:
        assert office._ordered_presentation_slides(z) == [
            'ppt/slides/slide2.xml', 'ppt/slides/slide10.xml',
        ]
        html = office._presentation_html(z)
    assert 'First ' in html and 'Later' not in html and 'rogue' not in html
    assert 'Preview truncated' in html
