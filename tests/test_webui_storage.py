"""Contract tests for the Python LibreChat-compatible persistence layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository(SQLiteDatabase(tmp_path / ".local-shell-mcp"))


def test_project_and_conversation_roundtrip(repo: WorkspaceRepository) -> None:
    project = repo.create_project("user-a", "Research", "Experiments", color="blue")
    assert len(project["_id"]) == 24
    assert project["color"] == "blue"
    convo = repo.create_conversation("user-a", {"title": "Example", "projectId": project["_id"], "endpoint": "agents", "memory": True})
    assert convo["title"] == "Example"
    assert convo["memory"] is True
    assert convo["projectId"] == project["_id"]
    assert repo.conversation("user-b", convo["conversationId"]) is None
    assert repo.projects("user-a")["projects"][0]["_id"] == project["_id"]
    updated = repo.update_conversation("user-a", convo["conversationId"], {"isArchived": True, "title": "Updated"})
    assert updated["isArchived"] is True
    assert updated["title"] == "Updated"
    assert repo.conversations("user-a", archived=True)["conversations"][0]["title"] == "Updated"
    assert repo.conversations("user-a")["conversations"] == []
    assert repo.update_conversation("user-b", convo["conversationId"], {"title": "Bypass"}) is None
    assert repo.delete_project("user-b", project["_id"]) is False
    assert repo.delete_project("user-a", project["_id"]) is True
    assert repo.conversation("user-a", convo["conversationId"])["projectId"] is None


def test_messages_pagination_and_search(repo: WorkspaceRepository) -> None:
    cid = repo.create_conversation("owner", {"title": "南京大学"})["conversationId"]
    for i in range(8):
        repo.add_message("owner", cid, {"role": "user", "text": f"南京大学问题 {i}", "messageId": f"m{i}"})
    page1 = repo.messages("owner", cid, limit=3)
    page2 = repo.messages("owner", cid, limit=3, cursor=page1["nextCursor"])
    page3 = repo.messages("owner", cid, limit=3, cursor=page2["nextCursor"])
    assert len(page1["messages"]) == 3
    assert len(page2["messages"]) == 3
    assert len(page3["messages"]) == 2
    assert not set(m["messageId"] for m in page1["messages"]) & set(m["messageId"] for m in page2["messages"])
    assert len(repo.search_messages("owner", "南京大")) == 8
    assert len(repo.search_messages("owner", "大学")) == 8
    assert repo.search_messages("another", "南京大") == []
    assert len(repo.conversations("owner", search="南京大学")["conversations"]) == 1
    assert repo.delete_conversation("owner", cid) is True
    assert repo.search_messages("owner", "南京大") == []
    with pytest.raises(KeyError):
        repo.messages("owner", cid)


def test_conversation_owner_isolation(repo: WorkspaceRepository) -> None:
    cid = repo.create_conversation("alice", {"title": "Private"})["conversationId"]
    with pytest.raises(KeyError):
        repo.add_message("bob", cid, {"text": "attack"})
    assert repo.delete_conversation("bob", cid) is False
    assert repo.conversation("alice", cid)["title"] == "Private"


def test_conversation_cursor_is_stable(repo: WorkspaceRepository) -> None:
    for i in range(6):
        repo.create_conversation("owner", {"title": f"Chat {i}"})
    seen: list[str] = []
    cursor = None
    while True:
        page = repo.conversations("owner", limit=2, cursor=cursor)
        seen.extend(item["conversationId"] for item in page["conversations"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 6


def test_user_settings_are_namespaced(repo: WorkspaceRepository) -> None:
    repo.save_setting("alice", "chat", {"model": "gpt-4.1"})
    assert repo.setting("alice", "chat")["model"] == "gpt-4.1"
    assert repo.setting("bob", "chat") is None


def test_delete_turn_splices_regenerated_branches_and_invalidates_summary(repo):
    from local_shell_mcp.webui.generations import GenerationStore

    owner = "alice"
    cid = repo.create_conversation(owner, {})["conversationId"]

    def add(mid, role, parent, **extra):
        return repo.add_message(owner, cid, {"messageId": mid, "role": role,
                                            "parentMessageId": parent, "text": mid, **extra})

    add("first", "user", None)
    add("first-reply", "assistant", "first")
    add("remove", "user", "first-reply")
    add("remove-reply", "assistant", "remove")
    add("retry-reply", "assistant", "remove")
    add("next", "user", "remove-reply")
    add("next-reply", "assistant", "next", content=[
        {"type": "summary", "content": "removed secret"},
        {"type": "text", "text": "next-reply"},
    ])
    add("other-branch", "user", "retry-reply")
    with repo.database.connect() as db:
        db.execute("INSERT INTO webui_message_bookmarks(owner,message_id,title,created_at) VALUES(?,?,?,?)",
                   (owner, "remove-reply", "bookmark", 1))
    with pytest.raises(KeyError):
        repo.delete_message_turn("bob", cid, "remove")
    assert repo.delete_message_turn(owner, cid, "remove-reply") == [
        "remove", "remove-reply", "retry-reply"]
    messages = {m["messageId"]: m for m in repo.messages(owner, cid)["messages"]}
    assert set(messages) == {"first", "first-reply", "next", "next-reply", "other-branch"}
    assert messages["next"]["parentMessageId"] == "first-reply"
    assert messages["other-branch"]["parentMessageId"] == "first-reply"
    assert messages["next-reply"]["content"] == [{"type": "text", "text": "next-reply"}]
    assert GenerationStore(repo.database).history(owner, cid, message_id="next-reply") == [
        {"role": "user", "content": "first"}, {"role": "assistant", "content": "first-reply"},
        {"role": "user", "content": "next"}, {"role": "assistant", "content": "next-reply"}]
    with repo.database.connect() as db:
        assert db.execute("SELECT count(*) FROM webui_message_bookmarks").fetchone()[0] == 0


def test_delete_generated_turn_and_block_active_run(repo):
    from local_shell_mcp.webui.generations import GenerationStore

    store = GenerationStore(repo.database)
    first, _ = store.begin("alice", {"text": "first"})
    cid = first.conversation_id
    with pytest.raises(ValueError, match="generation"):
        repo.delete_message_turn("alice", cid, first.user_message_id)
    store.finish("alice", first.run_id, status="complete", text="first reply")
    second, _ = store.begin("alice", {"text": "second", "conversationId": cid,
                                      "clientRequestId": "second-request"})
    store.finish("alice", second.run_id, status="complete", text="second reply")
    assert set(repo.delete_message_turn("alice", cid, second.user_message_id)) == {
        second.user_message_id, second.response_message_id}
    assert store.latest("alice", cid).run_id == first.run_id
    with pytest.raises(KeyError, match="deleted"):
        store.begin("alice", {"text": "second", "conversationId": cid,
                              "clientRequestId": "second-request"})
    with pytest.raises(KeyError, match="ancestor"):
        store.begin("alice", {"text": "stale", "conversationId": cid,
                              "parentMessageId": second.response_message_id})
    assert [m["content"] for m in store.history("alice", cid)] == ["first", "first reply"]
    assert set(repo.delete_message_turn("alice", cid, first.response_message_id)) == {
        first.user_message_id, first.response_message_id}
    assert store.latest("alice", cid) is None
    assert store.history("alice", cid) == []


def test_delete_turn_preserves_descendant_live_checkpoint_steps(repo):
    from local_shell_mcp.webui.generations import GenerationStore

    store = GenerationStore(repo.database)
    first, _ = store.begin("alice", {"text": "old prompt"})
    store.finish("alice", first.run_id, status="complete", text="old answer")
    second, _ = store.begin("alice", {"text": "keep prompt", "conversationId": first.conversation_id,
                                     "parentMessageId": first.response_message_id})
    call = {"id": "kept", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
    retained = [
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "kept", "content": "canonical full result"},
        {"role": "user", "source": "steer", "steerId": "kept-steer", "content": "keep steering"},
    ]
    store.stage_summary(
        "alice", second.run_id, "old secret summary", 10, live=True,
        retained_tail=[{"role": "user", "content": "old prompt"},
                       {"role": "assistant", "content": "old answer"},
                       {"role": "user", "content": "keep prompt"}, *retained],
        visible_text_boundary=0, model_history_start=7,
    )
    final = {"role": "assistant", "content": "keep answer"}
    store.finish("alice", second.run_id, status="complete", text="keep answer", model_steps=[final])
    repo.delete_message_turn("alice", first.conversation_id, first.user_message_id)
    assert store.history("alice", first.conversation_id, message_id=second.response_message_id) == [
        {"role": "user", "content": "keep prompt"}, *retained, final,
    ]
