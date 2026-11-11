"""Pinned upstream Artifact mode generation and Python SQLite runtime integration."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from local_shell_mcp.webui.artifact_prompts import (
    _source,
    agent_instructions,
    artifact_mode,
    generate_artifacts_prompt,
)
from local_shell_mcp.webui.generations import GenerationStore

PINNED = "e8f3be08623663d4ad7f7241e693c94469b63bb0"
# SHA-256 of the original TypeScript functions executed with upstream dedent 1.7.0.
ORIGINAL_NODE_GOLDENS = {
    "openai|default": "601eb7f4def11e76f0cc8e640d8b874ca1c7123264b501c9e327530892020bc8",
    "openai|shadcnui": "74086a840cbcfde186777b93e9b271bd1e994cf3f5a9e55ea12b1805841224eb",
    "anthropic|default": "d966d0510c64b20fc00a390c2a157e41f4e054a51ea315f804572780874b596f",
    "anthropic|shadcnui": "e074ac1d39b0f4582d9b7521c75379fdd1565b38829447af0197f12cfc086062",
}
UPSTREAM = Path("/root/librechat-reference-e8f3be08")


def test_snapshot_matches_source_hashes_when_upstream_checkout_present():
    data = _source()
    assert data["sourceCommit"] == PINNED
    assert len(data["components"]) == 33
    assert data["prompts"]["openai"].startswith(
        "The assistant can create and reference artifacts during conversations."
    )
    assert set(data["sourceSha256"]) == {
        "packages/api/src/prompts/artifacts/index.ts",
        "packages/api/src/prompts/artifacts/components.ts",
    }
    for path, digest in data["sourceSha256"].items():
        assert len(digest) == 64
        if (UPSTREAM / path).exists():
            assert hashlib.sha256((UPSTREAM / path).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("endpoint", ["openai", "anthropic", "google", "openai-compatible"])
@pytest.mark.parametrize("mode", ["default", "shadcnui", "custom", "", None, "unknown"])
def test_original_artifact_modes(endpoint, mode):
    generated = generate_artifacts_prompt(endpoint, mode)
    if mode == "custom":
        assert generated is None
    else:
        source = _source()["prompts"]["anthropic" if endpoint == "anthropic" else "openai"]
        assert generated.startswith(source)
        if mode == "shadcnui":
            assert "## Additional Artifact Instructions for React Components" in generated
            assert all(item["name"] in generated for item in _source()["components"])
            assert (
                "<component>" in generated if endpoint == "anthropic" else "# Avatar" in generated
            )
        else:
            assert generated == source
    key = f"{endpoint}|{mode}"
    if key in ORIGINAL_NODE_GOLDENS:
        assert hashlib.sha256(generated.encode()).hexdigest() == ORIGINAL_NODE_GOLDENS[key]


def test_prompt_state_and_delegation_instructions():
    saved = {"instructions": "System", "additional_instructions": "Other", "artifacts": "default"}
    assert artifact_mode({}, saved) == "default"
    assert artifact_mode({"ephemeralAgent": {"artifacts": "custom"}}, saved) == "custom"
    assert artifact_mode({"ephemeralAgent": {"artifacts": ""}}, saved) == ""
    assert artifact_mode({"ephemeralAgent": {"artifacts": "shadcnui"}}, None) == "shadcnui"
    assert agent_instructions(saved, "anthropic") == (
        "System\n\nOther\n\n" + _source()["prompts"]["anthropic"]
    )
    assert agent_instructions(saved, "anthropic", "") == "System\n\nOther"
    assert agent_instructions(None, "openai") == ""
    assert agent_instructions({"artifacts": ""}, "openai") == ""
    assert "application/vnd.react" in agent_instructions(saved, "openai", "shadcnui")


def test_exporter_is_repeatable_when_upstream_checkout_present():
    if not (UPSTREAM / "packages/api/src/prompts/artifacts/index.ts").exists():
        pytest.skip("Pinned upstream checkout not available in CI")
    script = Path(__file__).resolve().parents[1] / "scripts/export-librechat-artifact-prompts.py"
    spec = importlib.util.spec_from_file_location("artifact_prompt_exporter", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.snapshot(UPSTREAM) == _source()


def test_artifact_ephemeral_mode_snapshotted_for_resumable_generation(tmp_path):
    from local_shell_mcp.sqlite_store import SQLiteDatabase

    store = GenerationStore(SQLiteDatabase(tmp_path / ".local-shell-mcp"))
    agent = {"artifacts": "default"}
    job, fresh = store.begin(
        "local",
        {
            "text": "Make a diagram",
            "ephemeralAgent": {
                "artifacts": "shadcnui",
            },
        },
        agent,
    )
    assert fresh is True
    with store.database.connect() as db:
        state = json.loads(
            db.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0]
        )
    assert state["artifactsMode"] == "shadcnui"
    same, fresh = store.begin(
        "local",
        {"text": "Make a diagram", "clientRequestId": "same", "ephemeralAgent": {"artifacts": ""}},
    )
    assert fresh is True
    with store.database.connect() as db:
        other = json.loads(
            db.execute("SELECT state FROM runs WHERE id=?", (same.run_id,)).fetchone()[0]
        )
    assert other["artifactsMode"] == ""


@pytest.mark.asyncio
async def test_live_artifact_generation_sse_persistence_and_next_turn(tmp_path, monkeypatch):
    """Generation prompts, durable content, delta events, editing and next model history."""
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.sqlite_store import shared_database
    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.providers import ProviderConfig

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path),
        "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "none",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir.resolve())
    store = GenerationStore(database)
    profile = ProviderConfig("openai", "test", "http://127.0.0.1:11434/v1/chat/completions", "")
    source = (
        ':::artifact{identifier="h" type="text/html" title="Hello HTML"}\n'
        "```html\n<p>old</p>\n```\n:::"
    )
    seen = []

    async def stream(_profile, history, **_kwargs):
        seen.append(history.copy())
        if history[-1]["content"] == "Continue":
            assert "<p>new</p>" in history[-2]["content"]
            yield "Edited HTML read back."
        else:
            assert history[0]["role"] == "system"
            assert "application/vnd.react" in history[0]["content"]
            for part in (source[:55], source[55:]):
                yield part

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", stream)
    first, _ = store.begin(
        "local", {"text": "Create an HTML artifact", "ephemeralAgent": {"artifacts": "default"}}
    )
    try:
        await generation_routes._start_task("local", first, profile, None, artifacts_mode="default")
        await asyncio.gather(*generation_routes._TASKS.values())
        assert store.latest("local", first.conversation_id).status == "complete"
        events = [value for _, value in store.events("local", first.run_id)]
        chunks = [
            e["data"]["delta"]["content"]["text"]
            for e in events
            if e.get("event") == "on_message_delta"
        ]
        assert "".join(chunks) == source
        assert events[-1]["responseMessage"]["text"] == source
        assert events[-1]["responseMessage"]["content"][0]["text"] == source
        from local_shell_mcp.webui.artifact_routes import _update
        from local_shell_mcp.webui.storage import WorkspaceRepository

        update = _update(
            WorkspaceRepository(database),
            "local",
            first.response_message_id,
            0,
            "<p>old</p>",
            "<p>new</p>",
        )
        assert update.status_code == 200
        next_run, _ = store.begin(
            "local",
            {
                "conversationId": first.conversation_id,
                "text": "Continue",
                "parentMessageId": first.response_message_id,
                "ephemeralAgent": {"artifacts": "custom"},
            },
        )
        await generation_routes._start_task(
            "local", next_run, profile, None, artifacts_mode="custom"
        )
        await asyncio.gather(*generation_routes._TASKS.values())
        assert (
            store.events("local", next_run.run_id)[-1][1]["responseMessage"]["text"]
            == "Edited HTML read back."
        )
        assert len(seen) == 2
        assert seen[1][0]["role"] != "system"
    finally:
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cancelled_artifact_stream_preserves_partial_event_and_persistence(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.sqlite_store import shared_database
    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.providers import ProviderConfig

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path),
        "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "none",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir.resolve())
    store = GenerationStore(database)
    profile = ProviderConfig("openai", "test", "http://127.0.0.1:11434/v1/chat/completions", "")
    first_delta = asyncio.Event()

    async def stream(_profile, _history, **_kwargs):
        yield ':::artifact{identifier="partial" type="text/html" title="Incomplete"}\n'
        first_delta.set()
        await asyncio.Event().wait()
        yield "<p>Should not arrive</p>"

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", stream)
    run, _ = store.begin("local", {"text": "Generate HTML"})
    try:
        await generation_routes._start_task("local", run, profile, None)
        await asyncio.wait_for(first_delta.wait(), timeout=3)
        task = generation_routes._TASKS[run.run_id]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        result = store.latest("local", run.conversation_id)
        assert result.status == "aborted"
        final = store.events("local", run.run_id)[-1][1]
        assert final["aborted"] is True
        assert ":::artifact" in final["responseMessage"]["text"]
        assert "Should not arrive" not in final["responseMessage"]["text"]
        assert store.history("local", run.conversation_id)[-1]["content"] == (
            final["responseMessage"]["text"]
        )
    finally:
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()
