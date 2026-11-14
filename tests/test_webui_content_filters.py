"""Source-scoped Python content filtering: block, audit, bounded traversal."""
from __future__ import annotations

import pytest

from local_shell_mcp.webui.content_filters import (
    ContentFilterBlocked,
    ContentFragment,
    _nested_strings,
    filtered_tool_output,
    inspect_content,
    model_message_fragments,
    tool_fragments,
    validate_agent_instructions,
    validate_message_submission,
    validate_tool_arguments,
)


def _policy(source: str, *, action: str = 'block', fields=None, starter=None, custom=None):
    pii = {'action': action, 'starterPatterns': ['bearer_header'] if starter is None else starter,
           'customPatterns': [] if custom is None else custom}
    if fields is not None:
        pii['fields'] = fields
    return {source: {'pii': pii}}


def test_unconfigured_policy_does_not_change_any_user_or_provider_content():
    assert inspect_content([ContentFragment('message', 'content_part', 'Bearer secret-token')], None) is None
    assert inspect_content([ContentFragment('message', 'content_part', 'Bearer secret-token')], {}) is None
    assert filtered_tool_output('shell', 'Bearer private', None) == 'Bearer private'
    assert model_message_fragments([{'role': 'user', 'content': 'hello'}, {'role': 'tool',
        'content': 'output'}, {'role': 'assistant', 'content': None}, {'role': 'system',
        'content': 'system'}]) == [
            ContentFragment('assembled_context', 'assembled_context', 'hello', 'user'),
            ContentFragment('assembled_context', 'assembled_context', 'output', 'tool'),
            ContentFragment('assembled_context', 'assembled_context', 'system', 'system')]


def test_source_and_field_scopes_do_not_cross_pollinate():
    filters = _policy('messages', fields=['content_part'])
    assert inspect_content([ContentFragment('tool_argument', 'output', 'Bearer private')], filters) is None
    assert inspect_content([ContentFragment('assembled_context', 'assembled_context', 'Bearer private')], filters) is None
    with pytest.raises(ContentFilterBlocked) as exc:
        validate_message_submission('Bearer secret-token', filters)
    assert exc.value.response() == {'error': 'content_filter_block',
       'message': 'Submitted content was blocked by content policy.',
       'source': 'message', 'field': 'content_part'}
    assert 'secret-token' not in str(exc.value)
    assert inspect_content([ContentFragment('message', 'quote', 'Bearer secret-token')], filters) is None
    assert inspect_content([ContentFragment('message', 'content_part', 'nonmatching')], filters) is None


def test_custom_regex_match_nested_tool_args_and_tools_output():
    config = _policy('toolArguments', fields=['arguments', 'output'], starter=[], custom=[
        {'id': 'secret', 'label': 'internal-secret', 'regex': r'private_[0-9]+'}])
    with pytest.raises(ContentFilterBlocked):
        validate_tool_arguments('shell', {'query': ['no secret here', {'auth': 'private_100'}]}, config)
    result = filtered_tool_output('shell', 'private_555', config)
    assert result == 'Tool output withheld by configured content protection policy.'
    assert filtered_tool_output('shell', 'public', config) == 'public'
    name_only = _policy('toolArguments', fields=['name'], starter=[], custom=[
        {'id': 'name', 'label': 'blocked name', 'regex': 'shell'}])
    with pytest.raises(ContentFilterBlocked) as caught:
        validate_tool_arguments('shell', {}, name_only)
    assert caught.value.field == 'name'
    assert inspect_content(tool_fragments('safe', {'path': 'private_55'}), name_only) is None


def test_agent_instruction_configuration_has_separate_provenance():
    filters = _policy('agentInstructions', fields=['instructions'])
    with pytest.raises(ContentFilterBlocked) as caught:
        validate_agent_instructions('Use Bearer secret_001 for auth', filters)
    assert caught.value.source == 'agent_instruction'
    assert validate_agent_instructions('Use allowed tools', filters) is None
    assert validate_message_submission('Bearer secret_001', filters) is None


def test_audit_mode_logs_only_bounded_metadata_and_does_not_block():
    filters = _policy('messages', action='audit')
    fragments = [ContentFragment('message', 'content_part', 'Bearer private-SECRET')] * 10
    records = []
    assert inspect_content(fragments, filters, audit_sink=lambda **data: records.append(data)) is None
    assert len(records) == 1
    record = records[0]
    assert record['source'] == 'message' and record['field'] == 'content_part'
    assert record['action'] == 'audit' and record['ruleId'] == 'bearer_header'
    assert record['provenance'] == 'user' and record['occurrences'] == 10
    assert 'private-SECRET' not in str(record)


def test_cross_source_audit_and_block_preserve_safety_and_metadata():
    messages = _policy('messages', action='audit')
    arguments = _policy('toolArguments')
    filters = {**messages, **arguments}
    audit = []
    blocked = inspect_content([
        ContentFragment('message', 'content_part', 'Bearer user-SECRET'),
        ContentFragment('tool_argument', 'arguments', 'Bearer tool-SECRET', 'model')],
        filters, audit_sink=lambda **data: audit.append(data))
    assert isinstance(blocked, ContentFilterBlocked)
    assert blocked.source == 'tool_argument'
    assert len(audit) == 1 and audit[0]['source'] == 'message'
    assert 'SECRET' not in str(audit)


def test_invalid_pattern_policy_fails_closed_without_leaking_input():
    filters = _policy('messages', starter=[], custom=[
        {'id': 'unsupported', 'label': 'bad', 'regex': '(?=private)'}])
    with pytest.raises(ContentFilterBlocked):
        validate_message_submission('private-secret', filters)
    malformed = _policy('toolArguments', fields=['arguments'], starter=['unknown'])
    with pytest.raises(ContentFilterBlocked):
        validate_tool_arguments('shell', {'auth': 'anything'}, malformed)
    assert inspect_content([ContentFragment('message', 'content_part', 'anything')],
        _policy('messages', starter=[])) is None
    malformed_fields = _policy('messages', fields=['good', 2])
    with pytest.raises(ContentFilterBlocked):
        validate_message_submission('hello', malformed_fields)


def test_bounded_nested_keys_and_large_values_fail_closed_for_protected_field():
    filters = _policy('toolArguments', fields=['arguments'])
    deep = value = {}
    for _ in range(20):
        child = {}
        value['nested'] = child
        value = child
    assert _nested_strings({'x': ['secret', {'y': 'two'}]}) == ['x', 'secret', 'y', 'two']
    with pytest.raises(ValueError, match='budget'):
        _nested_strings(deep)
    with pytest.raises(ContentFilterBlocked):
        validate_tool_arguments('tool', {'data': deep}, filters)
    with pytest.raises(ContentFilterBlocked):
        validate_tool_arguments('tool', {'data': 'x' * 300_000}, filters)
    with pytest.raises(ContentFilterBlocked):
        validate_tool_arguments('tool', {'data': {'a': 'x'}}, _policy('toolArguments', starter=['unknown']))


def test_audit_config_broken_regex_cannot_make_read_or_write_fail():
    bad_audit = _policy('messages', action='audit', starter=[], custom=[
        {'id': 'invalid', 'label': 'wrong syntax', 'regex': '(?=rejected)'}])
    assert inspect_content([ContentFragment('message', 'content_part', 'rejected')], bad_audit) is None


def test_pattern_recognizes_all_original_content_source_categories():
    fields = {'prompts': 'prompt', 'conversationStarters': 'conversation_starter',
              'skills': 'skill', 'memories': 'memory', 'files': 'file',
              'modelParameters': 'model_parameter', 'actionMetadata': 'action_metadata',
              'feedback': 'feedback', 'conversationTitles': 'conversation_title'}
    for config_name, source in fields.items():
        # The pure inspector returns a finding instead of throwing; assert it
        # directly without the endpoint conversion layer.
        finding = inspect_content([ContentFragment(source, 'test_field', 'Bearer private')],
                                  _policy(config_name))
        assert finding is not None and finding.source == source


def test_model_parameter_fields_are_inspected_independently():
    from local_shell_mcp.webui.content_filters import validate_model_parameters

    filters = _policy('modelParameters', fields=['stop'], starter=[], custom=[
        {'id': 'secret_param', 'label': 'private value', 'regex': 'hidden_[0-9]+'}])
    with pytest.raises(ContentFilterBlocked) as caught:
        validate_model_parameters({'stop': ['hello', 'hidden_57']}, filters)
    assert caught.value.source == 'model_parameter' and caught.value.field == 'stop'
    assert validate_model_parameters({'metadata': {'secret': 'hidden_57'}}, filters) is None
    assert validate_model_parameters({'stop': ['valid']}, filters) is None


def test_source_global_custom_pattern_budget_fails_closed_for_active_source():
    filters = _policy('messages', starter=[], custom=[
        {'id': 'allowed', 'label': 'marker', 'regex': 'private'}])
    # Additional unrelated source policies can exhaust the global budget.
    filters.update(_policy('modelParameters', starter=[], custom=[
        {'id': f'k{i}', 'label': 'marker', 'regex': 'x'} for i in range(256)]))
    with pytest.raises(ContentFilterBlocked) as error:
        validate_message_submission('no secrets', filters)
    assert error.value.source == 'message'


def test_too_many_inspection_fragments_fail_closed():
    fragments = [ContentFragment('message', 'content_part', 'not matching') for _ in range(4098)]
    with pytest.raises(ContentFilterBlocked):
        inspect_content(fragments, _policy('messages'))


def test_bounded_policy_rejects_empty_invalid_fields_and_configuration():
    for fields in ([], [None], [2], [True], ['x' * 257], 'content_part'):
        policy = _policy('messages', fields=fields)
        with pytest.raises(ContentFilterBlocked):
            validate_message_submission('normal input', policy)
    disabled = _policy('messages', fields=['content_part'], starter=[])
    assert inspect_content([ContentFragment('message', 'content_part', 'Bearer x')], disabled) is None


def test_non_typed_fragment_is_never_silently_scanned():
    with pytest.raises(TypeError, match='typed content'):
        inspect_content([object()], _policy('messages'))


def test_global_budget_rejects_non_list_custom_source_configuration():
    filters = _policy('messages', starter=['bearer_header'])
    filters.update({'actionMetadata': {'pii': {'customPatterns': {'malformed': True}}}})
    with pytest.raises(ContentFilterBlocked):
        validate_message_submission('normal input', filters)


def test_audit_aggregates_field_provenance_and_rule_separately():
    filters = _policy('messages', action='audit', starter=['sk_prefix', 'bearer_header'])
    records = []
    fragments = [
        ContentFragment('message', 'content_part', 'Bearer PRIVATE-1 sk-valid_123', 'user'),
        ContentFragment('message', 'content_part', 'Bearer PRIVATE-2', 'model'),
        ContentFragment('assembled_context', 'assembled_context', 'sk-other_444', 'tool'),
    ]
    result = inspect_content(fragments, filters, audit_sink=lambda **data: records.append(data))
    assert result is None
    assert len(records) == 4
    assert set(item['provenance'] for item in records) == {'user', 'tool', 'model'}
    assert all('PRIVATE' not in str(row) and 'sk-valid_' not in str(row) for row in records)


def test_oversized_model_parameter_nested_data_is_fail_closed():
    from local_shell_mcp.webui.content_filters import validate_model_parameters

    config = _policy('modelParameters', fields=['metadata'])
    long = {'metadata': {'a': 'x' * 300_000}}
    with pytest.raises(ContentFilterBlocked):
        validate_model_parameters(long, config)
    assert validate_model_parameters(long, None) is None
    assert validate_agent_instructions('', _policy('agentInstructions')) is None


def test_audit_logger_failure_cannot_denial_of_service_a_permitted_generation():
    filters = _policy('messages', action='audit')

    def broken_sink(**_):
        raise OSError('logging backend unavailable')

    assert inspect_content([ContentFragment('message', 'content_part', 'Bearer SECRET')],
                           filters, audit_sink=broken_sink) is None
