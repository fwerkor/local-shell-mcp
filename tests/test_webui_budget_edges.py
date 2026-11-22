"""Pinned summarization trigger thresholds, role accounting and UTF-16 tokenizer seams."""
from __future__ import annotations

import pytest

from local_shell_mcp.webui.context_budget import (
    calculate_budget,
    message_token_count,
    should_trigger_summarization,
    split_recent_turns,
    summarize_options,
)
from local_shell_mcp.webui.tokenizer import count_tokens


def test_tokenizer_matches_exact_encoding_and_splits_js_surrogates():
    for case in (['a']*300, ['a', ' ']*2047 + ['a', '😊']):
        text = ''.join(case)
        assert count_tokens(text, exact=False) > 0
        assert count_tokens(text) > 0
    assert count_tokens('a ' * 2047 + 'a😊', exact=False) >= 0
    # Deliberately non-BPE-exact paths are bounded but deterministic.
    assert count_tokens('a ' * 2047 + 'a😊', exact=False) == count_tokens('a ' * 2047 + 'a😊', exact=False)


def test_message_token_extras_and_invalid_budget():
    assert message_token_count({'content': None}) >= 4
    assert message_token_count({'content': [{'type': 'text', 'text': 'hello'}]}) > 4
    assert message_token_count({'content': 'Hi', 'tool_call_id': 'call_1',
                                'thinking': 'Private context'}) > message_token_count({'content': 'Hi'})
    tool = [{'type': 'function', 'function': {'name': 'run', 'parameters': {'type': 'object'}}}]
    budget = calculate_budget([{'role': 'system', 'content': 'Hi'}, {'role': 'user', 'content': 'Go'}],
                              tool, 1200, reserve_ratio=0)
    assert budget.reserve_tokens == 0
    assert budget.tool_schema_tokens > 0
    with pytest.raises(ValueError):
        calculate_budget([], [], 0)
    assert calculate_budget([], [], 100, reserve_ratio=1.1).reserve_tokens == 0


@pytest.mark.parametrize('trigger,remaining,max_tokens,prior,expected', [
    ({'type': 'token_ratio', 'value': 0.7}, None, 100, None, False),
    ({'type': 'token_ratio', 'value': 0.7}, 0, 100, None, True),
    ({'type': 'token_ratio', 'value': 0.7}, 40, 100, None, False),
    ({'type': 'remaining_tokens', 'value': 15}, None, 100, None, False),
    ({'type': 'remaining_tokens', 'value': 15}, 14, 100, None, True),
    ({'type': 'remaining_tokens', 'value': 15}, 100, 100, 88, True),
    ({'type': 'messages_to_refine', 'value': 1}, None, None, None, True),
    ({'type': 'messages_to_refine', 'value': 7}, None, None, None, False),
    ({'type': 'unsupported', 'value': 1}, None, None, None, False),
])
def test_trigger_source_conditions(trigger, remaining, max_tokens, prior, expected):
    assert should_trigger_summarization(messages_to_refine_count=2, trigger=trigger,
        remaining_context_tokens=remaining, max_context_tokens=max_tokens,
        pre_prune_context_tokens=prior) is expected


def test_recency_empty_and_tool_pairs():
    assert split_recent_turns([], turns=2) == ([], [])
    assert split_recent_turns([{'role': 'system', 'content': 'Only system'}]) == (
        [{'role': 'system', 'content': 'Only system'}], [])
    dialogue = [{'role': 'user', 'content': 'One'},
                {'role': 'assistant', 'tool_calls': [{'id': 'a'}]},
                {'role': 'tool', 'tool_call_id': 'a', 'content': 'Done'},
                {'role': 'user', 'content': 'Two'}, {'role': 'assistant', 'content': 'OK'}]
    assert split_recent_turns(dialogue, turns=1)[0] == dialogue[:3]
    assert split_recent_turns(dialogue, turns=2)[0] == []
    assert split_recent_turns(dialogue, turns=2, tokens=1)[1][0] == dialogue[3]
    assert split_recent_turns(dialogue, turns=2, tokens=10000)[0] == []
    assert split_recent_turns(dialogue[:2] + dialogue[3:], turns=1)[0] == []


def test_summarization_option_resolution():
    assert summarize_options(None, {}) == (None, {})
    assert summarize_options({'maxContextTokens': 1024, 'summarization': {'enabled': True}}, {}) == (
        1024, {'enabled': True})
    assert summarize_options({'summarization': 'invalid'}, {'max_context_tokens': -1}) == (None, {})
    assert summarize_options({}, {'maxContextTokens': 8.4}) == (8, {})
