"""Graph member OAuth grants must not be attributed to the originating root."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import action_oauth, generation_routes
from local_shell_mcp.webui.action_spec import normalize_action_tool_name, tool_name
from local_shell_mcp.webui.actions import ActionRepository
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_controller_settings")
async def test_graph_member_oauth_recovers_with_child_action_binding(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / 'state')
    store = GenerationStore(db)
    repo = AgentRepository(db)
    root = repo.create('local', {'name': 'Graph root', 'provider': 'openAI', 'model': 'root'})
    child = repo.create('local', {'name': 'OAuth child', 'provider': 'openAI', 'model': 'child'})
    root = repo.update('local', root['id'], {'edges': [
        {'from': root['id'], 'to': child['id'], 'edgeType': 'direct'}]})
    base = 'https://action.example.invalid'
    definition = {'openapi': '3.0.0', 'servers': [{'url': base}],
                  'paths': {'/records': {'get': {'operationId': 'fetchRecord',
                                                'responses': {'200': {}}}}}}
    child, action = ActionRepository(db).save('local', child['id'], {
        'metadata': {'domain': base, 'raw_spec': json.dumps(definition),
                     'auth': {'type': 'oauth', 'authorization_url': 'https://id.example.invalid/auth',
                              'client_url': 'https://id.example.invalid/token', 'scope': 'read',
                              'token_exchange_method': 'default_post'},
                     'oauth_client_id': 'id', 'oauth_client_secret': 'secret'},
        'functions': [{'type': 'function', 'function': {'name': 'fetchRecord'}}],
    })
    tool = normalize_action_tool_name(tool_name('fetchRecord', base))
    job, _ = store.begin('local', {'text': 'Fetch through graph'}, root)
    namespace = '/graph:' + child['id'] + ':activation-1'
    pending = {'actionId': 'oauth-pending', 'namespace': namespace, 'payload': {
        'type': 'action_oauth', 'action_id': action['action_id'],
        'action_version': action['version'], 'tool_call_id': 'call-oauth', 'tool_name': tool}}
    assert store.pause_for_question('local', job.run_id, pending, [], '')
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    monkeypatch.setattr(generation_routes, '_generation_store', lambda: store)
    from local_shell_mcp.webui import machine_permissions
    from local_shell_mcp.webui.storage import WorkspaceRepository

    monkeypatch.setattr(machine_permissions, 'resolve_access', lambda *args, **kwargs: {})
    from local_shell_mcp.webui import routes
    monkeypatch.setattr(routes, '_repo', lambda: WorkspaceRepository(db))
    monkeypatch.setattr(generation_routes, 'provider_config', lambda *_: ProviderConfig(
        'openai', 'root', 'https://example.invalid', ''))
    from local_shell_mcp.webui import checkpoints

    monkeypatch.setattr(checkpoints.SQLiteCheckpointSaver, 'get_tuple',
        lambda *_: {'checkpoint': {'channel_values': {
            'pending_calls': [{'call_id': 'call-oauth', 'name': tool}]}}})

    async def token_exists(*_):
        return 'access-token'

    monkeypatch.setattr(action_oauth, 'access_token', token_exists)
    claimed = []

    async def restart(owner, generation, profile, agent, **kwargs):
        claimed.append((agent['id'], kwargs['resume_namespace'], kwargs['oauth_claim']))
        return True

    monkeypatch.setattr(generation_routes, '_start_task', restart)
    assert await generation_routes._resume_ready_oauth('local', store.get('local', job.run_id),
                                                        set(), None) is True
    assert claimed == [(root['id'], namespace,
                        (action['action_id'], 'call-oauth', action['version'], True))]
    assert store.get('local', job.run_id).agent_id == root['id']
