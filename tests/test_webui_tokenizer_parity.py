"""Fixed Node o200k-base and exact original TypeScript chunk-loop vectors."""
import json
from pathlib import Path

import pytest

from local_shell_mcp.webui.tokenizer import count_tokens

VECTORS = json.loads((Path(__file__).parent / 'fixtures/librechat/tokenizer_vectors.json').read_text(encoding='utf-8'))['vectors']


@pytest.mark.parametrize('index', range(len(VECTORS)))
def test_js_o200k_base_token_parity(index):
    case = VECTORS[index]
    assert count_tokens(case['text']) == case['exact']
    assert count_tokens(case['text'], exact=False) == case['bounded']
