from __future__ import annotations

import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import conversation_titles as titles
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def setup(tmp_path):
    db = SQLiteDatabase(tmp_path)
    return db, GenerationStore(db), WorkspaceRepository(db)


def begin(store, cid="new", text="修复数据库缓存"):
    return store.begin("alice", {"conversationId": cid, "text": text, "model": "original"})[0]


@pytest.mark.asyncio
async def test_default_names_after_reply_once(setup):
    db, store, repo = setup
    job = begin(store)
    assert repo.conversation("alice", job.conversation_id)["title"] == "New chat"
    profile = ProviderConfig("openai", "original", "https://example.invalid", "")
    calls = []

    async def stream(config, messages, **kwargs):
        assert config.model == "original"
        assert config.session_id != job.conversation_id
        assert json.loads(messages[-1]["content"])["reply"] == "修好了"
        calls.append(config)
        yield "数据库缓存修复"

    update = await titles.generate_conversation_title(db, "alice", job, profile, "修好了", stream=stream)
    assert repo.conversation("alice", job.conversation_id)["title"] == "New chat"
    assert store.finish("alice", job.run_id, status="complete", text="修好了", title_update=update)
    assert store.events("alice", job.run_id)[-1][1]["conversation"]["title"] == "数据库缓存修复"
    assert repo.conversation("alice", job.conversation_id)["title"] == "数据库缓存修复"
    second = begin(store, job.conversation_id)
    assert await titles.generate_conversation_title(db, "alice", second, profile, "修好了", stream=stream) is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_disabled_and_every_turn_fixed_model(setup, monkeypatch):
    db, store, repo = setup
    job = begin(store)
    original = ProviderConfig("openai", "original", "https://example.invalid", "")
    fixed = ProviderConfig("anthropic", "fixed", "https://example.invalid", "")
    calls = []

    async def stream(config, messages, **kwargs):
        calls.append(config.model)
        yield "New task " + str(len(calls))

    repo.save_setting("alice", "user.preferences", {"conversationTitleMode": "off"})
    assert await titles.generate_conversation_title(db, "alice", job, original, "done", stream=stream) is None
    assert calls == []
    store.finish("alice", job.run_id, status="complete", text="done")
    from local_shell_mcp.webui import provider_profiles
    monkeypatch.setattr(provider_profiles, "profile", lambda _: {"models": ["fixed"]})
    monkeypatch.setattr(titles, "provider_config", lambda channel, model: fixed)
    repo.save_setting("alice", "user.preferences", {
        "conversationTitleMode": "every", "conversationTitleModel": json.dumps(["named", "fixed"]),
    })
    for expected in ("New task 1", "New task 2"):
        job = begin(store, job.conversation_id)
        update = await titles.generate_conversation_title(db, "alice", job, original, "done", stream=stream)
        store.finish("alice", job.run_id, status="complete", text="done", title_update=update)
        assert repo.conversation("alice", job.conversation_id)["title"] == expected
    assert calls == ["fixed", "fixed"]


@pytest.mark.asyncio
async def test_failure_and_concurrent_manual_rename(setup):
    db, store, repo = setup
    job = begin(store)
    profile = ProviderConfig("openai", "original", "https://example.invalid", "")

    async def broken(*args, **kwargs):
        raise RuntimeError("provider failure")
        yield ""

    assert await titles.generate_conversation_title(db, "alice", job, profile, "done", stream=broken) is None

    async def stream(*args, **kwargs):
        repo.update_conversation("alice", job.conversation_id, {"title": "Manual"})
        yield "Generated"

    update = await titles.generate_conversation_title(db, "alice", job, profile, "done", stream=stream)
    store.finish("alice", job.run_id, status="complete", text="done", title_update=update)
    assert repo.conversation("alice", job.conversation_id)["title"] == "Manual"


def test_abort_never_commits_title(setup):
    db, store, repo = setup
    job = begin(store)
    store.finish("alice", job.run_id, status="aborted", text="partial",
                 title_update=titles.TitleUpdate("New chat", "Generated", "once", ""))
    assert repo.conversation("alice", job.conversation_id)["title"] == "New chat"
