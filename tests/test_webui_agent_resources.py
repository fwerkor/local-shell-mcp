"""Pinned agent.ts resource operators retain their distinct revision semantics."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository


@pytest.fixture
def repo(tmp_path):
    return AgentRepository(SQLiteDatabase(tmp_path))


def agent(repo, owner="alice"):
    return repo.create(owner, {"name": "Resource agent", "provider": "openAI", "model": None})["id"]


def file(repo, identity, owner="alice"):
    with repo.database.connect() as db:
        db.execute("INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
                   (identity, owner, identity + ".txt", "/private/" + identity, "text/plain", "{}"))


@pytest.mark.parametrize("resource", ["context", "file_search", "ocr", "execute_code", "image_edit"])
def test_resource_add_to_set_prewrite_snapshot_and_unversioned_remove(repo, resource):
    ident = agent(repo)
    file(repo, "owned")
    added = repo.add_resource_file("alice", ident, resource, "owned")
    assert added["tools"] == [resource]
    assert added["tool_resources"][resource]["file_ids"] == ["owned"]
    assert added["version"] == 2
    snapshot = repo.versions("alice", ident)[0]
    assert snapshot["tool_resources"][resource]["file_ids"] == []
    assert resource not in snapshot.get("tools", [])
    # agent.ts isDuplicateVersion returns null for a pure operator update;
    # idempotent membership does not suppress the new pre-write revision.
    repeated = repo.add_resource_file("alice", ident, resource, "owned")
    assert repeated["version"] == 3
    assert repeated["tool_resources"][resource]["file_ids"] == ["owned"]
    assert repo.versions("alice", ident)[0]["tool_resources"][resource]["file_ids"] == ["owned"]
    removed = repo.remove_resource_files("alice", ident, [{"tool_resource": resource, "file_id": "owned"}] * 2)
    assert removed["version"] == 3
    assert len(repo.versions("alice", ident)) == 3
    assert removed["tools"] == [resource]
    assert removed["tool_resources"][resource]["file_ids"] == []
    assert repo.remove_resource_files("alice", ident, []) == removed


def test_resource_owner_validation_and_transaction_contract(repo):
    ident = agent(repo)
    file(repo, "foreign", "bob")
    file(repo, "owned")
    for owner, identity, blob, message in [("bob", ident, "owned", "Agent not found"),
            ("alice", "missing", "owned", "Agent not found"),
            ("alice", ident, "foreign", "Attachment not found"),
            ("alice", ident, "missing", "Attachment not found")]:
        with pytest.raises(KeyError, match=message):
            repo.add_resource_file(owner, identity, "context", blob)
    for resource, blob in [("unknown", "owned"), (None, "owned"), ("context", ""), ("context", None)]:
        with pytest.raises(ValueError):
            repo.add_resource_file("alice", ident, resource, blob)
    for values in [None, [None], [{"tool_resource": "bad", "file_id": "owned"}],
                   [{"tool_resource": "context", "file_id": ""}]]:
        with pytest.raises(ValueError):
            repo.remove_resource_files("alice", ident, values)
    with pytest.raises(KeyError, match="Agent not found"):
        repo.remove_resource_files("bob", ident, [])
    with repo.database.connect() as db:
        with pytest.raises(ValueError, match="active transaction"):
            repo.add_resource_file("alice", ident, "context", "owned", db=db)
        with pytest.raises(ValueError, match="active transaction"):
            repo.remove_resource_files("alice", ident, [], db=db)
    assert len(repo.versions("alice", ident)) == 1


@pytest.mark.asyncio
async def test_publisher_commits_resource_revision_with_blob_or_rolls_everything_back(repo, tmp_path, monkeypatch):
    from local_shell_mcp.webui import attachments

    ident = agent(repo)
    monkeypatch.setattr(attachments, "_repo", lambda: SimpleNamespace(database=repo.database))

    async def chunks():
        yield b"real resource bytes"

    created = await attachments.publish_attachment("alice", "context.txt", "text/plain", chunks(), tmp_path,
        file_id="published", bind=lambda db, blob: repo.add_resource_file("alice", ident, "context", blob, db=db))
    assert Path(created["path"]).read_bytes() == b"real resource bytes"
    assert repo.get("alice", ident)["tool_resources"]["context"]["file_ids"] == ["published"]
    with pytest.raises(KeyError, match="Agent not found"):
        await attachments.publish_attachment("alice", "rollback.txt", "text/plain", chunks(), tmp_path,
            file_id="rollback", bind=lambda db, blob: repo.add_resource_file("bob", ident, "context", blob, db=db))
    assert not list((tmp_path / "attachments").glob("**/*rollback.txt"))
    with repo.database.connect() as db:
        assert db.execute("SELECT 1 FROM attachments WHERE id='rollback'").fetchone() is None
    assert len(repo.versions("alice", ident)) == 2


def test_resource_concurrent_additions_keep_all_members_and_revisions(repo):
    ident = agent(repo)
    ids = ["parallel-" + str(i) for i in range(8)]
    for identity in ids:
        file(repo, identity)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda blob: repo.add_resource_file("alice", ident, "context", blob), ids))
    assert len(results) == 8
    assert sorted(repo.get("alice", ident)["tool_resources"]["context"]["file_ids"]) == sorted(ids)
    assert len(repo.versions("alice", ident)) == 9
    removed = repo.remove_resource_files("alice", ident, [{"tool_resource": "context", "file_id": v} for v in ids])
    assert removed["tool_resources"]["context"]["file_ids"] == []
    assert len(repo.versions("alice", ident)) == 9
