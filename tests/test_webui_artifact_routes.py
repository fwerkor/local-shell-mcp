"""Original artifact editor route: ownership, durable edits and failure atomicity."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import auth, routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def artifact_app(tmp_path, monkeypatch):
    monkeypatch.setattr(
        routes, "get_settings", lambda: SimpleNamespace(auth_mode="oauth", state_dir=tmp_path)
    )
    monkeypatch.setattr(auth, "get_settings", routes.get_settings)
    repo = routes._repo()
    convo = repo.create_conversation("alice", {"title": "Artifacts"})
    message = repo.add_message(
        "alice",
        convo["conversationId"],
        {
            "role": "assistant",
            "text": "Keep this top-level value",
            "content": [
                {
                    "type": "text",
                    "text": 'before 😀\n:::artifact{identifier="code"}\n```html\n<p>old</p>\n```\n:::',
                }
            ],
            "userSubmittedPaths": [
                "bad",
                None,
                "/earlier",
                "/earlier",
                "/" + "x" * 2048,
                "/" + "😀" * 1024,
            ],
            "toolCallMetadata": {"keep": True},
        },
    )
    application = Starlette(routes=routes.webui_routes())

    async def authenticated(scope, receive, send):
        owner = next(
            (value.decode() for key, value in scope.get("headers", []) if key == b"x-owner"), None
        )
        if owner:
            scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await application(scope, receive, send)

    return repo, convo, message, authenticated


@pytest.mark.asyncio
async def test_original_editor_contract_persists_only_selected_text(artifact_app):
    repo, convo, message, app = artifact_app
    endpoint = "/api/messages/artifact/" + message["messageId"]
    body = {"index": 0, "original": "<p>old</p>", "updated": "<p>new 🚀</p>"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(endpoint, json=body)).status_code == 401
        assert (
            await client.post(endpoint, headers={"x-owner": "bob"}, json=body)
        ).status_code == 404
        assert (
            await client.post(
                "/api/messages/artifact/missing", headers={"x-owner": "alice"}, json=body
            )
        ).status_code == 404
        response = await client.post(endpoint, headers={"x-owner": "alice"}, json=body)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "conversationId": convo["conversationId"],
            "text": message["text"],
            "content": [
                {"type": "text", "text": message["content"][0]["text"].replace("old", "new 🚀")}
            ],
        }
        reloaded = WorkspaceRepository(repo.database).messages("alice", convo["conversationId"])[
            "messages"
        ][0]
        assert reloaded["content"] == response.json()["content"]
        assert reloaded["userSubmittedPaths"] == ["/earlier", "/content/0/text"]
        assert reloaded["toolCallMetadata"] == {"keep": True}
        replay = GenerationStore(repo.database).history(
            "alice", convo["conversationId"], message_id=message["messageId"]
        )
        assert replay == [{"role": "assistant", "content": response.json()["content"][0]["text"]}]
        assert message["text"] not in replay[0]["content"]
        again = await client.post(
            endpoint,
            headers={"x-owner": "alice"},
            json={**body, "original": "new 🚀", "updated": "next"},
        )
        assert again.status_code == 200
        assert repo.messages("alice", convo["conversationId"])["messages"][0][
            "userSubmittedPaths"
        ] == ["/earlier", "/content/0/text"]


@pytest.mark.asyncio
async def test_invalid_edit_and_sql_failure_never_partially_change_message(artifact_app):
    repo, convo, message, app = artifact_app
    endpoint = "/api/messages/artifact/" + message["messageId"]
    body = {"index": 0, "original": "old", "updated": "new"}
    before = repo.messages("alice", convo["conversationId"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}
    ) as client:
        for change in (
            {"index": -1},
            {"index": True},
            {"index": 0.5},
            {"index": "0"},
            {"original": None},
            {"updated": {}},
            {"index": 1},
            {"original": "absent"},
        ):
            assert (await client.post(endpoint, json={**body, **change})).status_code == 400
            assert repo.messages("alice", convo["conversationId"]) == before
        with repo.database.connect() as db:
            db.execute(
                "CREATE TRIGGER fail_artifact BEFORE UPDATE ON messages BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END"
            )
        response = await client.post(endpoint, json=body)
        assert response.status_code == 500 and response.json() == {"error": "Internal server error"}
        assert repo.messages("alice", convo["conversationId"]) == before
        with repo.database.connect() as db:
            db.execute("DROP TRIGGER fail_artifact")
        assert (await client.post(endpoint, json=body)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", [False, True])
async def test_child_thread_artifacts_remain_view_only(artifact_app, reserved):
    repo, _, _, app = artifact_app
    payload = (
        {"subagentThread": {"parentConversationId": "parent"}}
        if not reserved
        else {"conversationId": "12345678-1234-8123-b123-123456789abc"}
    )
    convo = repo.create_conversation("alice", payload)
    message = repo.add_message("alice", convo["conversationId"], {"text": ":::artifact\nold\n:::"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}
    ) as client:
        response = await client.post(
            "/api/messages/artifact/" + message["messageId"],
            json={"index": 0, "original": "old", "updated": "changed"},
        )
        assert response.status_code == 409
        assert (
            repo.messages("alice", convo["conversationId"])["messages"][0]["text"]
            == message["text"]
        )


@pytest.mark.asyncio
async def test_legacy_text_artifact_edits_preserve_metadata(artifact_app):
    repo, convo, _, app = artifact_app
    message = repo.add_message(
        "alice",
        convo["conversationId"],
        {"text": ":::artifact\n$14\n:::", "userSubmittedPaths": None},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}
    ) as client:
        response = await client.post(
            "/api/messages/artifact/" + message["messageId"],
            json={"index": 0, "original": r"\$14", "updated": "$20"},
        )
        assert response.status_code == 200
        assert response.json()["text"] == ":::artifact\n$20\n:::"
        with repo.database.connect() as db:
            row = db.execute(
                "SELECT metadata FROM messages WHERE id=?", (message["messageId"],)
            ).fetchone()
        assert json.loads(row["metadata"])["userSubmittedPaths"] == ["/text"]


@pytest.mark.asyncio
async def test_cross_origin_editor_mutation_is_rejected(artifact_app):
    repo, convo, message, app = artifact_app
    before = repo.messages("alice", convo["conversationId"])
    endpoint = "/api/messages/artifact/" + message["messageId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}
    ) as client:
        body = {"index": 0, "original": "old", "updated": "changed"}
        for origin in ["https://evil.invalid", "null"]:
            assert (
                await client.post(endpoint, headers={"Origin": origin}, json=body)
            ).status_code == 403
            assert repo.messages("alice", convo["conversationId"]) == before
        assert (
            await client.post(endpoint, headers={"Origin": "http://test"}, json=body)
        ).status_code == 200


def test_unassigned_agent_is_omitted_from_retained_conversation_dto(artifact_app):
    repo, convo, _, _ = artifact_app
    assert "agent_id" not in convo
    assert "agent_id" not in repo.conversation("alice", convo["conversationId"])
    assigned = repo.create_conversation("alice", {"agent_id": "configured-agent"})
    assert assigned["agent_id"] == "configured-agent"


@pytest.mark.asyncio
async def test_owned_user_artifact_edit_reaches_model_history(artifact_app):
    repo, convo, _, app = artifact_app
    message = repo.add_message(
        "alice",
        convo["conversationId"],
        {
            "role": "user",
            "text": "display snapshot",
            "content": [{"type": "text", "text": ":::artifact\nold\n:::"}],
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}
    ) as client:
        response = await client.post(
            "/api/messages/artifact/" + message["messageId"],
            json={"index": 0, "original": "old", "updated": "fresh"},
        )
        assert response.status_code == 200
    history = GenerationStore(repo.database).history(
        "alice", convo["conversationId"], message_id=message["messageId"]
    )
    assert history == [{"role": "user", "content": ":::artifact\nfresh\n:::"}]


@pytest.mark.asyncio
async def test_active_owned_subagent_thread_blocks_artifact_edits_before_lineage_persisted(
    artifact_app,
):
    """Upstream guard.ts also queries activity, not just UUID/metadata."""
    from local_shell_mcp.webui.child_thread_activity import ActiveChildThreads

    repo, _, _, app = artifact_app
    parent = repo.create_conversation("alice", {"title": "Parent"})
    store = GenerationStore(repo.database)
    run, _ = store.begin("alice", {"conversationId": parent["conversationId"], "text": "delegate"})
    child = repo.create_conversation("alice", {"title": "Unmaterialized child thread"})
    message = repo.add_message(
        "alice",
        child["conversationId"],
        {
            "role": "assistant",
            "text": ":::artifact\nold\n:::",
        },
    )
    activity = ActiveChildThreads(repo.database)
    activity.activate("alice", child["conversationId"], run.run_id)
    activity.activate("alice", child["conversationId"], run.run_id)  # idempotent same-run
    for invalid in ("", None):
        with pytest.raises(ValueError):
            activity.activate("alice", invalid, run.run_id)
    intruder = repo.create_conversation("bob", {"title": "Other owner's child"})
    with pytest.raises(PermissionError, match="another owner"):
        activity.activate("alice", intruder["conversationId"], run.run_id)
    other_parent = repo.create_conversation("alice", {"title": "Other parent"})
    other_run, _ = store.begin(
        "alice",
        {"conversationId": other_parent["conversationId"], "text": "another active delegation"},
    )
    with pytest.raises(PermissionError, match="different parent run"):
        activity.activate("alice", child["conversationId"], other_run.run_id)
    assert store.finish("alice", other_run.run_id, status="complete", text="done")
    with pytest.raises(PermissionError, match="not active"):
        activity.activate("alice", "child-after-complete", other_run.run_id)
    with pytest.raises(PermissionError):
        activity.activate("bob", child["conversationId"], run.run_id)
    with pytest.raises(ValueError):
        activity.activate("alice", parent["conversationId"], run.run_id)
    with pytest.raises(PermissionError):
        activity.activate("alice", child["conversationId"], "fake")
    edit_url = "/api/messages/artifact/" + message["messageId"]
    payload = {"index": 0, "original": "old", "updated": "new"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}
    ) as client:
        assert (await client.post(edit_url, json=payload)).status_code == 409
        assert activity.settle("bob", child["conversationId"], run.run_id) is False
        assert (await client.post(edit_url, json=payload)).status_code == 409
        assert activity.settle("alice", child["conversationId"], run.run_id) is True
        assert (await client.post(edit_url, json=payload)).status_code == 200
        assert activity.settle("alice", child["conversationId"], run.run_id) is False


@pytest.mark.asyncio
async def test_concurrent_artifact_edits_cannot_overwrite_same_original(artifact_app):
    repo, _, _, app = artifact_app
    convo = repo.create_conversation("alice", {"title": "Concurrent editing"})
    message = repo.add_message(
        "alice", convo["conversationId"], {"role": "assistant", "text": ":::artifact\nbase\n:::"}
    )
    endpoint = "/api/messages/artifact/" + message["messageId"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}
    ) as client:
        changes = await asyncio.gather(
            client.post(endpoint, json={"index": 0, "original": "base", "updated": "winner A"}),
            client.post(endpoint, json={"index": 0, "original": "base", "updated": "winner B"}),
        )
    assert sorted(response.status_code for response in changes) == [200, 400]
    final = repo.messages("alice", convo["conversationId"])["messages"][0]["text"]
    assert final in {":::artifact\nwinner A\n:::", ":::artifact\nwinner B\n:::"}
