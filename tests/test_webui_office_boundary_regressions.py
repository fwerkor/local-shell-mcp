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
