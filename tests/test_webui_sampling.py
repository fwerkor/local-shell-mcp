"""Model defaults and ordinary-chat sampling must reach the native generation path."""
import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.sampling import merge_sampling, validate_sampling
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.mark.parametrize("value", [
    None, [], {"other": 1}, {"temperature": True}, {"temperature": -1},
    {"temperature": 2.1}, {"temperature": float("nan")}, {"top_p": 1.1},
    {"max_tokens": 0}, {"max_tokens": 1.5}, {"max_tokens": 2_000_001},
])
def test_invalid_sampling_rejected(value):
    with pytest.raises(ValueError):
        validate_sampling(value)


def test_sampling_inheritance_and_legacy_agent_aliases():
    defaults = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 256}
    assert validate_sampling({"temperature": 0, "top_p": 0, "max_tokens": 1}) == {
        "temperature": 0, "top_p": 0, "max_tokens": 1}
    assert merge_sampling(defaults, {"temperature": 0, "topP": 0.5,
                                     "maxOutputTokens": 100, "stop": ["END"]}) == {
        "temperature": 0, "top_p": 0.5, "max_tokens": 100, "stop": ["END"]}
    assert merge_sampling(defaults, {}) == defaults


def test_conversation_sampling_persists_and_reset_does_not_change_running_snapshot(tmp_path):
    db = SQLiteDatabase(tmp_path / "state")
    repo = WorkspaceRepository(db)
    store = GenerationStore(db)
    initial = {"temperature": 0, "max_tokens": 144}
    run, fresh = store.begin("owner", {"text": "hello", "model": "mock", "endpoint": "openAI",
                                      "lsmSampling": initial})
    assert fresh and run.sampling == initial
    assert store.get("owner", run.run_id).sampling == initial
    assert repo.conversation("owner", run.conversation_id)["lsmSampling"] == initial
    repo.update_conversation("owner", run.conversation_id, {"lsmSampling": {}})
    assert store.get("owner", run.run_id).sampling == initial
    store.finish("owner", run.run_id, status="complete", text="done")
    new, fresh = store.begin("owner", {"text": "next", "conversationId": run.conversation_id,
                                      "model": "mock", "endpoint": "openAI"})
    assert fresh and new.sampling == {}
    store.finish("owner", new.run_id, status="complete", text="done")
    new, fresh = store.begin("owner", {"text": "third", "conversationId": run.conversation_id,
                                      "model": "mock", "endpoint": "openAI", "lsmSampling": initial})
    assert fresh and new.sampling == initial
    assert repo.conversation("owner", run.conversation_id)["lsmSampling"] == initial
