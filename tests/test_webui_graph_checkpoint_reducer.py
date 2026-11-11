"""Source ID reductions and real SQLite LangGraph checkpoint APIs."""
from __future__ import annotations

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.message_reducers import (
    REMOVE_ALL_MESSAGES,
    agent_messages_reducer,
    create_remove_all_message,
    messages_state_reducer,
)

pytest.importorskip("langgraph")


def test_message_ids_types_clear_and_replacements():
    def mk(ident):
        return {"role": "user", "id": ident, "content": str(ident)}
    assert messages_state_reducer([mk(True)], [mk(1)]) == [mk(True), mk(1)]
    assert messages_state_reducer([mk(1)], [mk(1.0)]) == [mk(1.0)]
    assert messages_state_reducer([mk(False)], [mk(False)]) == [mk(False)]
    ident = object()
    assert messages_state_reducer([mk(ident)], [mk(ident)])[0]["id"] is ident
    assert messages_state_reducer([mk("a")], [None, mk("b")]) == [mk("a"), mk("b")]
    assert messages_state_reducer([mk("x")], create_remove_all_message()) == []
    assert create_remove_all_message() == {"type": "remove", "role": "remove", "id": REMOVE_ALL_MESSAGES}
    assert agent_messages_reducer([mk("old")], [mk("replacement")]) == [mk("replacement")]
    with pytest.raises(TypeError):
        messages_state_reducer([mk("a")], [3])


@pytest.mark.asyncio
async def test_owned_graph_saver_tuples_list_async_writes_and_owner_isolation(tmp_path, monkeypatch):
    from langgraph.types import Send

    from local_shell_mcp.webui.graph_checkpoint import OwnedGraphCheckpointer

    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    db = shared_database(get_settings().state_dir)
    saver = OwnedGraphCheckpointer(db, "alice")
    config = saver.storage.config("thread", "generation:graph", event_actor=True)
    assert saver.get_tuple(config) is None
    with pytest.raises(ValueError, match="thread config"):
        list(saver.list(None))
    state = {"id": "c1", "channel_values": {"messages": [{"id": "m1", "role": "user", "content": "hi"}]}}
    first = saver.put(config, state, {"source": "input", "step": 0}, {})
    assert saver.get_tuple(config).checkpoint == state
    async_sends = Send("child", {"messages": [{"id": "m2", "role": "user", "content": "go"}]})
    await saver.aput_writes(first, [("tasks", async_sends)], "task-1")
    second = await saver.aput(first, {**state, "id": "c2"}, {"source": "loop", "step": 1}, {})
    rows = list(saver.list(config))
    assert [row.checkpoint["id"] for row in rows] == ["c2", "c1"]
    assert len(list(saver.list(config, limit=1))) == 1
    assert [row.checkpoint["id"] for row in saver.list(config, before=second)] == ["c1"]
    async_rows = [row async for row in saver.alist(config)]
    assert [row.checkpoint["id"] for row in async_rows] == ["c2", "c1"]
    assert async_rows[-1].pending_writes[0][2] == async_sends
    assert (await saver.aget_tuple(second)).metadata["step"] == 1
    other = OwnedGraphCheckpointer(db, "bob")
    assert other.get_tuple(other.storage.config("thread", "generation:graph")) is None
    with pytest.raises(PermissionError):
        other.get_tuple(second)
    get_settings.cache_clear()


def test_graph_import_error_and_command_validation(monkeypatch):
    import builtins

    from langgraph.types import Send

    from local_shell_mcp.webui import graph_runtime

    orig_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name.startswith("langgraph.graph"):
            raise ImportError("simulated missing optional runtime")
        return orig_import(name, *args, **kwargs)

    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, "__import__", unavailable)
        with pytest.raises(RuntimeError, match="webui-graph"):
            graph_runtime._graph_imports()
    with pytest.raises(ValueError, match="Unknown source Command"):
        graph_runtime._as_goto([{"goto": [object()]}], Send=Send)
    assert graph_runtime._as_goto([{"goto": "node"}], Send=Send) == ["node"]
    assert graph_runtime._content({"content": {"text": "something"}}) == "{'text': 'something'}"
    assert len(graph_runtime._limit_prompt("x" * 1000, 10)) == 10
