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
