"""Missing new WebUI extras must never take down the Controller or native tools."""

from __future__ import annotations

import builtins
import logging
from pathlib import Path

import pytest

from local_shell_mcp.webui import office_preview, tokenizer
from local_shell_mcp.webui.context_budget import calculate_budget


@pytest.mark.parametrize('missing', ['tiktoken', 'regex'])
def test_missing_tokenizer_extra_preserves_conservative_context_budget(monkeypatch, caplog, missing):
    # Simulate either an absent tiktoken package or an unavailable transitive
    # dependency, even on a CI runner that installed every optional extra.
    def unavailable():
        raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)

    value = '你好, world! ' * 50
    monkeypatch.setattr(tokenizer, '_encoding', unavailable)
    tokenizer._warn_missing_encoding.cache_clear()
    try:
        with caplog.at_level(logging.WARNING):
            for exact in (True, False):
                assert tokenizer.count_tokens(value, exact=exact) == len(value.encode('utf-8'))
            budget = calculate_budget([{'role': 'user', 'content': value}], [], 1000)
            assert budget.message_tokens == len(value.encode('utf-8')) + 4
            assert tokenizer.count_tokens('') == 0
        assert sum('tokenizer dependencies are unavailable' in rec.message for rec in caplog.records) == 1
    finally:
        tokenizer._warn_missing_encoding.cache_clear()


def test_missing_actual_tiktoken_import_does_not_break_counting(monkeypatch):
    original_import = builtins.__import__

    def import_without_tiktoken(name, *args, **kwargs):
        if name == 'tiktoken' or name.startswith('tiktoken.'):
            raise ModuleNotFoundError("No module named 'tiktoken'", name='tiktoken')
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, '__import__', import_without_tiktoken)
        tokenizer._encoding.cache_clear()
        assert tokenizer.count_tokens('Memory: 南京大学') == len('Memory: 南京大学'.encode())
    tokenizer._encoding.cache_clear()


@pytest.mark.asyncio
async def test_missing_xlrd_keeps_original_attachment_without_preview(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.sqlite_store import shared_database
    from local_shell_mcp.webui.generations import GenerationStore

    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    try:
        database = shared_database(tmp_path / 'state')
        generation, _ = GenerationStore(database).begin('local', {'text': 'Create an XLS'})
        content = (Path(__file__).parent / 'fixtures/librechat/office/sample.xls').read_bytes()
        original_import = builtins.__import__

        def import_without_xlrd(name, *args, **kwargs):
            if name == 'xlrd' or name.startswith('xlrd.'):
                raise ModuleNotFoundError("No module named 'xlrd'", name='xlrd')
            return original_import(name, *args, **kwargs)

        with monkeypatch.context() as isolated:
            isolated.setattr(builtins, '__import__', import_without_xlrd)
            result = await office_preview.publish_office_tool_output(
                'local', generation.run_id, 'xls-call', 'data.xls',
                'application/vnd.ms-excel', content,
                database=database, state_dir=tmp_path / 'state',
            )
        assert result['status'] == 'failed'
        assert result['previewError'] == 'unsupported'
        with database.connect() as connection:
            row = connection.execute('SELECT path FROM attachments WHERE id=?',
                                     (result['file_id'],)).fetchone()
            assert row is not None
            assert Path(row['path']).read_bytes() == content
        events = [entry for _, entry in GenerationStore(database).events('local', generation.run_id)]
        assert any(event.get('event') == 'attachment' for event in events)
    finally:
        get_settings.cache_clear()


def test_missing_xlrd_preview_is_a_handled_error(monkeypatch):
    original_import = builtins.__import__

    def import_without_xlrd(name, *args, **kwargs):
        if name == 'xlrd' or name.startswith('xlrd.'):
            raise ModuleNotFoundError("No module named 'xlrd'", name='xlrd')
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, '__import__', import_without_xlrd)
        with pytest.raises(ValueError, match='requires xlrd'):
            office_preview.buffer_to_office_html(b'\xd0\xcf\x11\xe0broken',
                                                 'data.xls', 'application/vnd.ms-excel')
