"""Approval preferences and conservative tool classification."""
import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.approval_settings import (
    CHAT_PREFIX,
    GLOBAL_KEY,
    call_decision,
    effective_mode,
    validate_mode,
)
from local_shell_mcp.webui.misc_routes import misc_routes
from local_shell_mcp.webui.routes import _repo


class Settings:
    def __init__(self):
        self.data = {}

    def setting(self, owner, key, default=None):
        return self.data.get((owner, key), default)


def test_approval_mode_precedence_and_parent_ceiling():
    repo = Settings()
    assert effective_mode(repo, "owner", "chat") == "automatic"
    repo.data["owner", GLOBAL_KEY] = "dangerous"
    assert effective_mode(repo, "owner", "chat") == "dangerous"
    assert effective_mode(repo, "owner", "chat", {"approval_mode": "automatic"}) == "automatic"
    assert effective_mode(repo, "owner", "chat", {"approval_mode": "automatic"}, parent_mode="all") == "all"
    repo.data["owner", CHAT_PREFIX + "chat"] = "automatic"
    assert effective_mode(repo, "owner", "chat", {"approval_mode": "all"}, parent_mode="all") == "automatic"
    assert effective_mode(repo, "other", "chat") == "automatic"
    repo.data["owner", CHAT_PREFIX + "chat"] = "inherit"
    assert effective_mode(repo, "owner", "chat", {"approval_mode": "all"}) == "all"


@pytest.mark.parametrize("name,args,review", [
    ("file_read", {}, False),
    ("file_write", {}, True),
    ("run_shell", {"command": "ls"}, False),
    ("run_shell", {"command": "pwd"}, False),
    ("run_shell", {"command": "ls > out"}, True),
    ("run_shell", {"command": "ls; rm x"}, True),
    ("run_shell", {"command": "rm x"}, True),
    ("run_shell", {"command": ["ls"]}, True),
    ("run_python", {}, True),
    ("shell_send", {}, True),
    ("web_search", {}, False),
    ("web_fetch", {}, False),
    ("browser_session", {"action": "list"}, False),
    ("browser_session", {"action": ["list"]}, True),
    ("session_manage", {"action": "start"}, False),
    ("session_manage", {"action": "delete"}, True),
    ("plan_manage", {"action": "get"}, False),
    ("plan_manage", {"action": "cancel"}, True),
    ("subagent", {}, False),
    ("unknown_mcp", {}, True),
])
def test_risk_policy(name, args, review):
    assert call_decision("automatic", None, name, args) is None
    assert call_decision("dangerous", None, name, args) == ({"decision": "ask"} if review else None)
    assert call_decision("all", None, name, args) == {"decision": "ask"}


def test_question_and_legacy_policy():
    assert call_decision("all", None, "ask_user_question", {}) is None
    policy = {"enabled": True, "mode": "bypass", "deny": ["file_write"], "ask": ["run_shell"]}
    assert call_decision("automatic", policy, "file_write", {}) == {"decision": "deny"}
    assert call_decision("automatic", policy, "run_shell", {}) == {"decision": "ask"}
    assert call_decision("all", policy, "file_read", {}) == {"decision": "ask"}
    assert call_decision("all", {"enabled": True, "ask": ["ask_user_question"]}, "ask_user_question", {}) == {"decision": "ask"}
    assert validate_mode("inherit", inherit=True) == "inherit"
    for bad in (None, True, "inherit", [], {}):
        with pytest.raises(ValueError):
            validate_mode(bad)


@pytest.mark.asyncio
async def test_preferences_api_and_agent_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    try:
        repo = _repo()
        agents = AgentRepository(repo.database)
        agent = agents.create("local", {"name": "Reviewed", "provider": "openAI", "model": "test", "approval_mode": "all"})
        assert agents.get("local", agent["id"])["approval_mode"] == "all"
        from local_shell_mcp.webui.generations import GenerationStore
        generation, _ = GenerationStore(repo.database).begin("local", {"text": "test", "agent_id": agent["id"]}, agent)
        url = "/api/lsm/approval/" + generation.conversation_id
        app = Starlette(routes=misc_routes())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/lsm/approval")).json() == {"mode": "automatic", "effective": "automatic"}
            assert (await client.put("/api/lsm/approval", json={"mode": "dangerous"})).status_code == 200
            assert (await client.get(url)).json() == {"mode": "inherit", "effective": "all"}
            assert (await client.put(url, json={"mode": "automatic"})).json() == {"mode": "automatic", "effective": "automatic"}
            assert effective_mode(repo, "local", generation.conversation_id, agent, parent_mode="all") == "all"
            assert (await client.put(url, json={"mode": "inherit"})).json() == {"mode": "inherit", "effective": "all"}
            assert (await client.put(url, json={"mode": "bad"})).status_code == 400
            assert (await client.put("/api/lsm/approval", json={"mode": "inherit"})).status_code == 400
            assert (await client.get("/api/lsm/approval/not-owned")).status_code == 404
            assert (await client.put("/api/lsm/approval/not-owned", json={"mode": "all"})).status_code == 404
        assert _repo().setting("local", GLOBAL_KEY) == "dangerous"
    finally:
        get_settings.cache_clear()
