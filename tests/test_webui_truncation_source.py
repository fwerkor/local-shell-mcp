"""Pinned agents@4.0.1 truncation.ts direct TypeScript differential vectors."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from local_shell_mcp.webui.truncation_source import (
    truncate_tool_input,
    truncate_tool_result_content,
)


def vectors():
    path = Path(__file__).parent / 'fixtures' / 'webui_truncation_source_vectors.json.gz'
    with gzip.open(path, 'rt', encoding='utf-8') as source:
        return json.load(source)


@pytest.mark.parametrize('test', vectors())
def test_original_typescript_truncation_contract(test):
    value = test['input']['text']
    budget = test['input']['budget']
    assert truncate_tool_input(value, budget) == test['expected']['input']
    assert truncate_tool_result_content(value, budget) == test['expected']['result']


def test_short_content_and_structured_input_preserve_original():
    structured = {'text': 'concise', 'values': [1, 2]}
    expected = json.dumps(structured, separators=(',', ':'), ensure_ascii=False)
    assert truncate_tool_input(structured, 500) == {'_truncated': expected, '_originalChars': len(expected)}
    assert truncate_tool_result_content('short', 500) == 'short'
