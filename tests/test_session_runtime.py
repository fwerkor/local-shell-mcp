from __future__ import annotations

import threading
import time

import pytest

from local_shell_mcp.session_runtime import (
    PLAN_CONTINUATION_CLAIM_ID_LIMIT,
    PLAN_CONTINUATION_FAILURE_BACKOFF_S,
    PLAN_EXECUTION_LEASE_S,
    PLAN_MAX_STEPS,
    PLAN_NOTE_LIMIT,
    PLAN_OBJECTIVE_LIMIT,
    PLAN_STEP_ID_LIMIT,
    PLAN_STEP_TEXT_LIMIT,
    SESSION_ACTIVITY_LIMIT,
    SESSION_HISTORY_LIMIT_PER_PRINCIPAL,
    SESSION_IN_FLIGHT_LEASE_S,
    SESSION_STALE_AFTER_S,
    SessionRuntimeManager,
)
from local_shell_mcp.settings import get_settings
from local_shell_mcp.state_store import MemoryStateStore, clear_memory_state


def _reserve_claim(
    manager: SessionRuntimeManager, session_id: str, *, subject: str | None = None
) -> dict:
    claimed = manager.claim_plan_continuation(session_id, subject=subject)
    assert claimed is not None
    validation = manager.validate_plan_continuation(
        session_id, claimed["claim_id"], subject=subject
    )
    assert validation["valid"] is True
    return claimed


def test_session_progress_and_plan_survive_manager_reload(tmp_path):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage(
        "user", action="start", label="PR work", objective="Implement durable logical sessions"
    )
    session_id = started["session_id"]
    manager.manage(
        "user",
        action="report",
        session_id=session_id,
        summary="Runtime is implemented",
        findings=["Live channels must not own plans"],
        next="Run integration tests",
        blockers=[],
    )
    manager.manage_plan(
        session_id,
        action="start",
        objective="Ship the change",
        steps=[{"id": "test", "text": "Run tests"}],
    )
    restored = SessionRuntimeManager(state_dir)
    state = restored.manage("user", action="get", session_id=session_id)
    assert state["label"] == "PR work"
    assert state["objective"] == "Implement durable logical sessions"
    assert state["progress"]["summary"] == "Runtime is implemented"
    assert state["progress"]["findings"] == ["Live channels must not own plans"]
    assert state["plan"]["objective"] == "Ship the change"
    assert any(event["type"] == "session.reported" for event in state["recent_activity"])


def test_completed_session_can_resume_after_manager_reload(tmp_path):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Durable task")
    session_id = started["session_id"]
    manager.manage(
        "user", action="report", session_id=session_id, summary="Initial work complete"
    )
    manager.manage("user", action="finish", session_id=session_id)

    restored = SessionRuntimeManager(state_dir)
    resumed = restored.manage("user", action="resume", session_id=session_id)

    assert resumed["status"] == "active"
    assert resumed["progress"]["summary"] == "Initial work complete"
    assert resumed["recent_activity"][-1]["type"] == "session.resumed"
    reported = restored.manage(
        "user", action="report", session_id=session_id, summary="Follow-up work started"
    )
    assert reported["progress"]["summary"] == "Follow-up work started"


def test_cancelled_session_cannot_resume(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Abandoned task")
    session_id = started["session_id"]
    manager.manage("user", action="cancel", session_id=session_id)

    with pytest.raises(ValueError, match="Cannot resume a cancelled session"):
        manager.manage("user", action="resume", session_id=session_id)


def test_session_list_is_principal_scoped_sorted_and_compact(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    older = manager.manage("user", action="start", label="Older")
    other = manager.manage("other-user", action="start", label="Private")
    time.sleep(0.001)
    newer = manager.manage("user", action="start", label="Newer")
    manager.manage("user", action="report", session_id=newer["session_id"], summary="checkpoint")

    sessions = manager.list_sessions(subject="user")

    assert [item["session_id"] for item in sessions] == [newer["session_id"], older["session_id"]]
    assert all(item["session_id"] != other["session_id"] for item in sessions)
    assert all(item["recent_activity"] == [] for item in sessions)
    assert manager.get(newer["session_id"], subject="user")["recent_activity"]


def test_session_list_requires_subject(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    with pytest.raises(ValueError, match="subject is required"):
        manager.list_sessions(subject="")


def test_session_list_supports_trusted_unscoped_human_view_and_actor(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    first = manager.manage("alpha", action="start", label="First", actor="human")
    second = manager.manage("beta", action="start", label="Second")
    manager.manage("alpha", action="cancel", session_id=first["session_id"], actor="human")

    sessions = manager.list_sessions(subject=None)

    assert {item["session_id"] for item in sessions} == {first["session_id"], second["session_id"]}
    detail = manager.get(first["session_id"])
    assert detail["recent_activity"][0]["actor"] == "human"
    assert detail["recent_activity"][-1]["actor"] == "human"


def test_session_public_state_exposes_full_rolling_activity_window(tmp_path):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Exercise the activity window")
    session_id = started["session_id"]
    for index in range(SESSION_ACTIVITY_LIMIT + 5):
        manager.manage(
            "user", action="report", session_id=session_id, summary=f"checkpoint {index}"
        )
    state = manager.get(session_id)
    activity = state["recent_activity"]
    assert len(activity) == SESSION_ACTIVITY_LIMIT
    assert activity[-1]["data"]["summary"] == f"checkpoint {SESSION_ACTIVITY_LIMIT + 4}"
    assert activity[0]["seq"] == activity[-1]["seq"] - SESSION_ACTIVITY_LIMIT + 1
    restored = SessionRuntimeManager(state_dir).get(session_id)
    assert len(restored["recent_activity"]) == SESSION_ACTIVITY_LIMIT


def test_session_report_rolls_back_when_persistence_fails(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage("user", action="report", session_id=session_id, summary="before")
    original_save = manager._save_locked
    failed = False

    def fail_report_once(session):
        nonlocal failed
        if (
            not failed
            and session.activity
            and (session.activity[-1]["type"] == "session.reported")
            and (session.progress.summary == "after")
        ):
            failed = True
            raise OSError("report persistence failed")
        return original_save(session)

    monkeypatch.setattr(manager, "_save_locked", fail_report_once)
    with pytest.raises(OSError, match="report persistence failed"):
        manager.manage("user", action="report", session_id=session_id, summary="after")
    assert manager.get(session_id)["progress"]["summary"] == "before"
    assert SessionRuntimeManager(state_dir).get(session_id)["progress"]["summary"] == "before"


def test_plan_fields_are_bounded_before_persistence(tmp_path):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    oversized_id = "i" * (PLAN_STEP_ID_LIMIT + 200)
    plan = manager.manage_plan(
        session_id,
        action="start",
        objective="o" * (PLAN_OBJECTIVE_LIMIT + 200),
        steps=[
            {
                "id": oversized_id,
                "text": "t" * (PLAN_STEP_TEXT_LIMIT + 200),
                "note": "n" * (PLAN_NOTE_LIMIT + 200),
            }
        ],
    )["plan"]
    assert len(plan["objective"]) == PLAN_OBJECTIVE_LIMIT
    assert len(plan["steps"][0]["id"]) == PLAN_STEP_ID_LIMIT
    assert len(plan["steps"][0]["text"]) == PLAN_STEP_TEXT_LIMIT
    assert len(plan["steps"][0]["note"]) == PLAN_NOTE_LIMIT
    updated = manager.manage_plan(
        session_id,
        action="update",
        objective="u" * (PLAN_OBJECTIVE_LIMIT + 200),
        step_id=oversized_id,
        text="x" * (PLAN_STEP_TEXT_LIMIT + 200),
        note="y" * (PLAN_NOTE_LIMIT + 200),
    )["plan"]
    assert len(updated["objective"]) == PLAN_OBJECTIVE_LIMIT
    assert len(updated["steps"][0]["text"]) == PLAN_STEP_TEXT_LIMIT
    assert len(updated["steps"][0]["note"]) == PLAN_NOTE_LIMIT
    blocked = manager.manage_plan(session_id, action="block", note="b" * (PLAN_NOTE_LIMIT + 200))[
        "plan"
    ]
    assert len(blocked["note"]) == PLAN_NOTE_LIMIT
    manager.manage_plan(session_id, action="resume")
    manager.manage_plan(session_id, action="update", step_id=oversized_id, status="completed")
    finished = manager.manage_plan(session_id, action="finish", note="f" * (PLAN_NOTE_LIMIT + 200))[
        "plan"
    ]
    assert len(finished["note"]) == PLAN_NOTE_LIMIT
    restored = SessionRuntimeManager(state_dir).manage(
        "user", action="get", session_id=started["session_id"]
    )["plan"]
    assert len(restored["objective"]) == PLAN_OBJECTIVE_LIMIT
    assert len(restored["steps"][0]["id"]) == PLAN_STEP_ID_LIMIT
    assert len(restored["steps"][0]["text"]) == PLAN_STEP_TEXT_LIMIT
    assert len(restored["steps"][0]["note"]) == PLAN_NOTE_LIMIT


def test_plan_activity_records_meaningful_change_details(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id,
        action="start",
        objective="Ship the UI",
        steps=[{"id": "impl", "text": "Implement UI"}, {"id": "test", "text": "Run tests"}],
    )
    manager.manage_plan(
        session_id, action="update", step_id="impl", status="completed", note="done"
    )
    session = manager.manage("user", action="get", session_id=session_id)
    updated = session["recent_activity"][-1]
    assert updated["type"] == "plan.updated"
    assert updated["data"]["objective"] == "Ship the UI"
    assert updated["data"]["completed_steps"] == 1
    assert updated["data"]["total_steps"] == 2
    assert updated["data"]["active_step"]["id"] == "test"
    assert updated["data"]["changes"]["updated_fields"] == ["status", "note"]
    assert updated["data"]["changes"]["step"] == {
        "id": "impl",
        "text": "Implement UI",
        "status": "completed",
        "note": "done",
    }
    manager.manage_plan(session_id, action="block", note="Need user input")
    blocked = manager.manage("user", action="get", session_id=session_id)["recent_activity"][-1]
    assert blocked["type"] == "plan.blocked"
    assert blocked["data"]["status"] == "blocked"
    assert blocked["data"]["reason"] == "Need user input"
    assert blocked["data"]["active_step"]["id"] == "test"


def test_plan_continuation_waits_for_inflight_and_backs_off(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    lease = manager.begin_tool_call(session_id, "call-1", data={"tool": "remote_transfer"})
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    assert manager.claim_plan_continuation(session_id, subject="user") is None
    assert manager.finish_tool_call(lease, "tool.completed", data={"ok": True}) is None
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    claimed = _reserve_claim(manager, session_id, subject="user")
    failed = manager.report_plan_continuation(
        session_id,
        accepted=False,
        error="host unavailable",
        claim_id=claimed["claim_id"],
        subject="user",
    )
    assert failed["continuation_count"] == 1
    assert failed["continuation_retry_after"] is not None
    assert (
        failed["continuation_retry_after"] >= time.time() + PLAN_CONTINUATION_FAILURE_BACKOFF_S - 1
    )
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    assert manager.claim_plan_continuation(session_id, subject="user") is None
    logical.plan.continuation_retry_after = time.time() - 1
    assert manager.claim_plan_continuation(session_id, subject="user") is not None


def test_unreserved_failed_continuation_report_releases_claim(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    claim = manager.claim_plan_continuation(session_id, subject="user")
    assert claim is not None
    assert logical.plan.continuation_reserved is False
    failed = manager.report_plan_continuation(
        session_id,
        accepted=False,
        error="model context update failed",
        claim_id=claim["claim_id"],
        subject="user",
    )
    assert failed["continuation_pending"] is False
    assert failed["continuation_reserved"] is False
    assert failed["continuation_count"] == 0
    assert failed["continuation_retry_after"] is not None


def test_continuation_claim_can_be_recovered_after_response_loss(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    with pytest.raises(ValueError, match="claim_id must be"):
        manager.claim_plan_continuation(
            session_id, claim_id="x" * (PLAN_CONTINUATION_CLAIM_ID_LIMIT + 1), subject="user"
        )
    first = manager.claim_plan_continuation(session_id, claim_id="c_retry", subject="user")
    assert first is not None
    assert first["claim_id"] == "c_retry"
    recovered = manager.claim_plan_continuation(session_id, claim_id="c_retry", subject="user")
    assert recovered is not None
    assert recovered["claim_id"] == first["claim_id"]
    assert recovered["continuation_count"] == first["continuation_count"] == 1
    assert manager.claim_plan_continuation(session_id, claim_id="c_other", subject="user") is None


def test_reserved_continuation_claim_recovery_does_not_double_count(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    claim = manager.claim_plan_continuation(session_id, claim_id="c_retry", subject="user")
    assert claim is not None
    first_validation = manager.validate_plan_continuation(session_id, "c_retry", subject="user")
    assert first_validation["valid"] is True
    assert first_validation["plan"]["continuation_count"] == 1
    recovered = manager.claim_plan_continuation(session_id, claim_id="c_retry", subject="user")
    assert recovered is not None
    assert recovered["continuation_count"] == 1
    second_validation = manager.validate_plan_continuation(session_id, "c_retry", subject="user")
    assert second_validation["valid"] is True
    assert second_validation["plan"]["continuation_count"] == 1


def test_tool_start_persistence_failure_fails_closed(tmp_path, monkeypatch):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]

    def fail_save(_session):
        raise OSError("disk full")

    monkeypatch.setattr(manager, "_save_locked", fail_save)
    with pytest.raises(RuntimeError, match="refusing to execute"):
        manager.begin_tool_call(session_id, "call-1", subject="user")
    assert manager._sessions[session_id].in_flight_calls == {}


def test_tool_completion_persists_lease_removal_before_optional_activity(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    lease = manager.begin_tool_call(session_id, "call-1")
    assert lease is not None
    original_save = manager._save_locked
    save_count = 0

    def fail_completion_activity(session):
        nonlocal save_count
        save_count += 1
        if save_count == 2:
            raise OSError("transient completion activity failure")
        return original_save(session)

    monkeypatch.setattr(manager, "_save_locked", fail_completion_activity)
    error = manager.finish_tool_call(lease, "tool.completed", data={"ok": True})
    assert error is not None and "transient completion activity failure" in error
    restored_manager = SessionRuntimeManager(state_dir)
    restored_manager.get(session_id, subject="user")
    assert restored_manager._sessions[session_id].in_flight_calls == {}


def test_sessions_use_configured_stateless_state_backend(tmp_path, monkeypatch):
    clear_memory_state()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "memory")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX", "session-runtime-test")
    get_settings.cache_clear()
    try:
        manager = SessionRuntimeManager()
        started = manager.manage("user", action="start", objective="Task")
        restored = SessionRuntimeManager().manage(
            "user", action="get", session_id=started["session_id"]
        )
        assert restored["objective"] == "Task"
        assert not (tmp_path / ".state" / "sessions").exists()
    finally:
        get_settings.cache_clear()
        clear_memory_state()


def test_shared_backend_refreshes_sessions_across_controller_instances(tmp_path, monkeypatch):
    clear_memory_state()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "redis")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_URL", "redis://state.test/0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX", "shared-session-runtime-test")
    get_settings.cache_clear()
    shared_store = MemoryStateStore("shared-session-runtime-test")
    monkeypatch.setattr("local_shell_mcp.session_runtime.get_state_store", lambda: shared_store)
    try:
        first = SessionRuntimeManager()
        second = SessionRuntimeManager()
        started = first.manage("user", action="start", objective="Shared task")
        session_id = started["session_id"]
        assert (
            second.manage("user", action="get", session_id=session_id)["objective"] == "Shared task"
        )
        second.manage("user", action="resume", session_id=session_id)
        first.manage("user", action="report", session_id=session_id, summary="first update")
        second.manage("user", action="report", session_id=session_id, summary="fresh state")
        refreshed = first.manage("user", action="get", session_id=session_id)
        assert refreshed["progress"]["summary"] == "fresh state"
    finally:
        get_settings.cache_clear()
        clear_memory_state()


def test_shared_backend_prunes_only_terminal_history_and_recovers_claims(tmp_path, monkeypatch):
    clear_memory_state()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "redis")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_URL", "redis://state.test/0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX", "shared-retention-test")
    monkeypatch.setattr("local_shell_mcp.session_runtime.SESSION_HISTORY_LIMIT_PER_PRINCIPAL", 2)
    get_settings.cache_clear()
    shared_store = MemoryStateStore("shared-retention-test")
    monkeypatch.setattr("local_shell_mcp.session_runtime.get_state_store", lambda: shared_store)
    try:
        manager = SessionRuntimeManager()
        terminal = manager.manage("user", action="start", objective="Terminal")
        manager.manage("user", action="finish", session_id=terminal["session_id"])
        resumable = manager.manage("user", action="start", objective="Resumable")
        current = manager.manage("user", action="start", objective="Current")
        with pytest.raises(ValueError, match="Unknown logical session"):
            manager.get(terminal["session_id"], subject="user")
        assert manager.get(resumable["session_id"], subject="user")["status"] == "active"
        manager.manage_plan(
            current["session_id"],
            action="start",
            objective="Current",
            steps=[{"id": "work", "text": "Work"}],
        )
        logical = manager._sessions[current["session_id"]]
        assert logical.plan is not None
        logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
        manager._save_locked(logical)
        claimed = manager.claim_plan_continuation(
            current["session_id"], claim_id="c_shared_retry", subject="user"
        )
        recovered = manager.claim_plan_continuation(
            current["session_id"], claim_id="c_shared_retry", subject="user"
        )
        assert claimed is not None
        assert recovered is not None
        assert recovered["claim_id"] == claimed["claim_id"] == "c_shared_retry"
    finally:
        get_settings.cache_clear()
        clear_memory_state()


def test_shared_resume_rollback_snapshots_refreshed_previous_session(tmp_path, monkeypatch):
    clear_memory_state()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "redis")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_URL", "redis://state.test/0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX", "resume-rollback-refresh-test")
    get_settings.cache_clear()
    shared_store = MemoryStateStore("resume-rollback-refresh-test")
    monkeypatch.setattr("local_shell_mcp.session_runtime.get_state_store", lambda: shared_store)
    try:
        first = SessionRuntimeManager()
        previous = first.manage("user", action="start", objective="Previous")
        target = first.manage("user", action="start", objective="Target")
        previous_id = previous["session_id"]
        target_id = target["session_id"]
        external = SessionRuntimeManager()
        external.get(previous_id, subject="user")
        external._sessions[previous_id].progress.summary = "fresh external progress"
        external._save_locked(external._sessions[previous_id])
        assert first._sessions[previous_id].progress.summary is None
        original_save = first._save_locked
        failed = False

        def fail_target_resume_once(session):
            nonlocal failed
            if (
                not failed
                and session.session_id == target_id
                and session.activity
                and (session.activity[-1]["type"] == "session.resumed")
            ):
                failed = True
                raise OSError("target resume persistence failed")
            return original_save(session)

        monkeypatch.setattr(first, "_save_locked", fail_target_resume_once)
        with pytest.raises(OSError, match="target resume persistence failed"):
            first.manage("user", action="resume", session_id=target_id)
        durable = SessionRuntimeManager().get(previous_id, subject="user")
        assert durable["progress"]["summary"] == "fresh external progress"
    finally:
        get_settings.cache_clear()
        clear_memory_state()


def test_shared_backend_serializes_session_mutations_across_controllers(tmp_path, monkeypatch):
    clear_memory_state()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "redis")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_URL", "redis://state.test/0")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX", "session-rmw-lock-test")
    get_settings.cache_clear()
    shared_store = MemoryStateStore("session-rmw-lock-test")
    monkeypatch.setattr("local_shell_mcp.session_runtime.get_state_store", lambda: shared_store)
    try:
        first = SessionRuntimeManager()
        second = SessionRuntimeManager()
        started = first.manage("user", action="start", objective="Shared task")
        session_id = started["session_id"]
        first.manage_plan(
            session_id,
            action="start",
            objective="Shared task",
            steps=[{"id": "work", "text": "Work"}],
        )
        save_started = threading.Event()
        release_save = threading.Event()
        original_save = first._save_locked

        def pause_report_save(session):
            if threading.current_thread().name == "session-report":
                save_started.set()
                assert release_save.wait(2)
            original_save(session)

        monkeypatch.setattr(first, "_save_locked", pause_report_save)
        errors: list[BaseException] = []

        def report_progress() -> None:
            try:
                first.manage(
                    "user", action="report", session_id=session_id, summary="report survives"
                )
            except BaseException as exc:
                errors.append(exc)

        def block_plan() -> None:
            try:
                second.manage_plan(session_id, action="block", note="needs input", subject="user")
            except BaseException as exc:
                errors.append(exc)

        reporter = threading.Thread(target=report_progress, name="session-report")
        blocker = threading.Thread(target=block_plan, name="session-block")
        reporter.start()
        assert save_started.wait(1)
        blocker.start()
        time.sleep(0.1)
        release_save.set()
        reporter.join(2)
        blocker.join(2)
        assert not reporter.is_alive()
        assert not blocker.is_alive()
        assert errors == []
        restored = SessionRuntimeManager().get(session_id, subject="user")
        assert restored["progress"]["summary"] == "report survives"
        assert restored["plan"]["status"] == "blocked"
        assert restored["plan"]["note"] == "needs input"
    finally:
        get_settings.cache_clear()
        clear_memory_state()


def test_session_access_is_scoped_to_principal(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("alice", action="start", objective="Private task")
    with pytest.raises(PermissionError, match="different principal"):
        manager.manage("bob", action="get", session_id=started["session_id"])


def test_session_history_preserves_resumable_sessions_beyond_retention_target(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_ids: list[str] = []
    for index in range(SESSION_HISTORY_LIMIT_PER_PRINCIPAL + 1):
        started = manager.manage("user", action="start", objective=f"Task {index}")
        session_ids.append(started["session_id"])
    assert manager.get(session_ids[0], subject="user")["status"] == "active"
    assert len(manager._sessions) == SESSION_HISTORY_LIMIT_PER_PRINCIPAL + 1


def test_session_history_auto_prunes_oldest_terminal_session(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    terminal = manager.manage("user", action="start", objective="Old terminal")
    manager.manage("user", action="finish", session_id=terminal["session_id"])
    for index in range(SESSION_HISTORY_LIMIT_PER_PRINCIPAL):
        manager.manage("user", action="start", objective=f"Task {index}")
    assert len(manager._sessions) == SESSION_HISTORY_LIMIT_PER_PRINCIPAL
    with pytest.raises(ValueError, match="Unknown logical session"):
        manager.get(terminal["session_id"], subject="user")


def test_session_delete_rejects_active_session(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    with pytest.raises(ValueError, match="active logical session"):
        manager.manage("user", action="delete", session_id=started["session_id"])


def test_session_initial_load_retries_after_transient_scan_failure(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    seeded = SessionRuntimeManager(state_dir).manage("user", action="start", objective="Persisted")
    manager = SessionRuntimeManager(state_dir)
    store = manager._state_store()

    class FlakyStore:
        def __init__(self, delegate):
            self.delegate = delegate
            self.failed = False

        def list_keys(self, prefix=""):
            if not self.failed:
                self.failed = True
                raise OSError("mount unavailable")
            return self.delegate.list_keys(prefix)

        def read_bytes(self, key):
            return self.delegate.read_bytes(key)

        def write_bytes(self, key, value):
            return self.delegate.write_bytes(key, value)

        def delete(self, key):
            return self.delegate.delete(key)

        def lock(self, key):
            return self.delegate.lock(key)

    flaky = FlakyStore(store)
    monkeypatch.setattr(manager, "_state_store", lambda: flaky)
    with pytest.raises(OSError, match="mount unavailable"):
        manager.get(seeded["session_id"], subject="user")
    assert manager._loaded_storage is None
    restored = manager.get(seeded["session_id"], subject="user")
    assert restored["objective"] == "Persisted"


def test_session_finish_requires_terminal_plan(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    with pytest.raises(ValueError, match="plan is active or blocked"):
        manager.manage("user", action="finish", session_id=session_id)
    manager.manage_plan(session_id, action="update", step_id="work", status="completed")
    manager.manage_plan(session_id, action="finish")
    finished = manager.manage("user", action="finish", session_id=session_id)
    assert finished["status"] == "completed"
    assert finished["session_id"] == session_id


def test_plan_validation_update_and_terminal_edges(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start")
    session_id = started["session_id"]
    assert manager.manage_plan(session_id, action="get")["plan"] is None
    with pytest.raises(ValueError, match="objective is required"):
        manager.manage_plan(session_id, action="start", objective=" ", steps=[])
    with pytest.raises(ValueError, match="at least one step"):
        manager.manage_plan(session_id, action="start", objective="Goal", steps=[])
    with pytest.raises(ValueError, match="at most"):
        manager._normalize_plan_steps([{"text": str(index)} for index in range(PLAN_MAX_STEPS + 1)])
    with pytest.raises(ValueError, match="unique"):
        manager._normalize_plan_steps(
            [{"id": "same", "text": "one"}, {"id": "same", "text": "two"}]
        )
    with pytest.raises(ValueError, match="has no text"):
        manager._normalize_plan_steps([{"id": "blank", "text": " "}])
    with pytest.raises(ValueError, match="Unsupported plan step status"):
        manager._normalize_plan_steps([{"text": "work", "status": "weird"}])
    with pytest.raises(ValueError, match="at most one active"):
        manager._normalize_plan_steps(
            [{"text": "one", "status": "active"}, {"text": "two", "status": "active"}]
        )
    plan = manager.manage_plan(
        session_id,
        action="start",
        objective="Goal",
        steps=[{"id": "a", "text": "A", "note": "note"}, {"id": "b", "text": "B"}],
    )
    assert plan["plan"]["steps"][0]["note"] == "note"
    with pytest.raises(ValueError, match="already active"):
        manager.manage_plan(session_id, action="start", objective="Again", steps=[{"text": "x"}])
    with pytest.raises(ValueError, match="objective cannot be empty"):
        manager.manage_plan(session_id, action="update", objective=" ")
    with pytest.raises(ValueError, match="Unknown plan step"):
        manager.manage_plan(session_id, action="update", step_id="missing", status="completed")
    with pytest.raises(ValueError, match="Unsupported plan step status"):
        manager.manage_plan(session_id, action="update", step_id="a", status="weird")
    with pytest.raises(ValueError, match="step text cannot be empty"):
        manager.manage_plan(session_id, action="update", step_id="a", text=" ")
    with pytest.raises(ValueError, match="step_id is required"):
        manager.manage_plan(session_id, action="update", status="completed")
    with pytest.raises(ValueError, match="action=update requires"):
        manager.manage_plan(session_id, action="update")
    updated = manager.manage_plan(
        session_id,
        action="update",
        objective="Revised",
        step_id="b",
        status="active",
        text="B revised",
        note="step note",
    )
    statuses = {step["id"]: step["status"] for step in updated["plan"]["steps"]}
    assert statuses == {"a": "pending", "b": "active"}
    assert updated["plan"]["objective"] == "Revised"
    assert updated["plan"]["steps"][1]["text"] == "B revised"
    assert updated["plan"]["steps"][1]["note"] == "step note"
    manager.manage_plan(session_id, action="update", note="plan note")
    manager.manage_plan(
        session_id,
        action="update",
        steps=[
            {"id": "done", "text": "Done", "status": "completed"},
            {"id": "skip", "text": "Skip", "status": "skipped"},
        ],
    )
    with pytest.raises(ValueError, match="note is required"):
        manager.manage_plan(session_id, action="block", note=" ")
    blocked = manager.manage_plan(session_id, action="block", note="human input")
    assert blocked["plan"]["status"] == "blocked"
    with pytest.raises(ValueError, match="Cannot block"):
        manager.manage_plan(session_id, action="block", note="again")
    resumed = manager.manage_plan(session_id, action="resume")
    assert resumed["plan"]["status"] == "active"
    with pytest.raises(ValueError, match="Only a blocked"):
        manager.manage_plan(session_id, action="resume")
    finished = manager.manage_plan(session_id, action="finish")
    assert finished["plan"]["status"] == "completed"
    with pytest.raises(ValueError, match="Cannot finish"):
        manager.manage_plan(session_id, action="finish")
    with pytest.raises(ValueError, match="already completed"):
        manager.manage_plan(session_id, action="cancel")
    with pytest.raises(ValueError, match="Cannot update"):
        manager.manage_plan(session_id, action="update", note="late")
    with pytest.raises(ValueError, match="action must be one of"):
        manager.manage_plan(session_id, action="unknown")
    terminal = manager.manage("user", action="finish", session_id=session_id)
    assert terminal["status"] == "completed"
    resumed_session = manager.manage("user", action="resume", session_id=session_id)
    assert resumed_session["status"] == "active"
    assert resumed_session["plan"]["status"] == "completed"
    assert resumed_session["recent_activity"][-1]["type"] == "session.resumed"


def test_plan_cancel_and_continuation_pending_expiry(tmp_path, monkeypatch):
    manager = SessionRuntimeManager(tmp_path / ".state")
    now = [10000.0]
    monkeypatch.setattr("local_shell_mcp.session_runtime.time.time", lambda: now[0])
    started = manager.manage("user", action="start", objective="Goal")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Goal", steps=[{"id": "work", "text": "Work"}]
    )
    now[0] += PLAN_EXECUTION_LEASE_S + 1
    assert manager.claim_plan_continuation(session_id) is not None
    now[0] += 5 * 60 + 1
    reclaimed = manager.claim_plan_continuation(session_id)
    assert reclaimed is not None
    assert manager.validate_plan_continuation(session_id, reclaimed["claim_id"])["valid"] is True
    manager.report_plan_continuation(session_id, accepted=True, claim_id=reclaimed["claim_id"])
    with pytest.raises(ValueError, match="No plan continuation is pending"):
        manager.report_plan_continuation(session_id, accepted=True)
    cancelled = manager.manage("user", action="cancel", session_id=session_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["plan"]["status"] == "cancelled"
    assert manager.claim_plan_continuation(session_id) is None
    no_plan = manager.manage("user", action="start", objective="No plan")
    with pytest.raises(ValueError, match="No plan exists"):
        manager.report_plan_continuation(no_plan["session_id"], accepted=False)


def test_human_resume_preserves_overdue_goal_lease(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Goal")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Goal", steps=[{"id": "work", "text": "Work"}]
    )
    manager.manage_plan(session_id, action="block", note="human input")
    overdue = time.time() - PLAN_EXECUTION_LEASE_S - 1
    manager._sessions[session_id].plan.last_agent_activity = overdue
    resumed = manager.manage_plan(session_id, action="resume", actor="human", subject="user")
    assert resumed["plan"]["last_agent_activity"] == overdue
    assert manager.claim_plan_continuation(session_id, subject="user") is not None


def test_completed_plan_steps_remain_eligible_for_cleanup_continuation(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    started = manager.manage("user", action="start", objective="Goal")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Goal", steps=[{"id": "work", "text": "Work"}]
    )
    manager.manage_plan(session_id, action="update", step_id="work", status="completed")
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    assert logical.plan.status == "active"
    assert logical.plan.has_unfinished_steps() is False
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    assert logical.plan.public_state()["continuation_due"] is True
    claimed = manager.claim_plan_continuation(session_id, subject="user")
    assert claimed is not None
    assert claimed["plan"]["status"] == "active"


def test_plan_mutation_rolls_back_when_persistence_fails(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="before", steps=[{"id": "work", "text": "Work"}]
    )
    original_save = manager._save_locked
    failed = False

    def fail_plan_update_once(session):
        nonlocal failed
        if not failed and session.activity and (session.activity[-1]["type"] == "plan.updated"):
            failed = True
            raise OSError("plan persistence failed")
        return original_save(session)

    monkeypatch.setattr(manager, "_save_locked", fail_plan_update_once)
    with pytest.raises(OSError, match="plan persistence failed"):
        manager.manage_plan(session_id, action="update", objective="after")
    assert manager.plan_state(session_id)["objective"] == "before"
    assert SessionRuntimeManager(state_dir).plan_state(session_id)["objective"] == "before"


def test_continuation_claim_rolls_back_when_persistence_fails(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    original_save = manager._save_locked
    failed = False

    def fail_claim_once(session):
        nonlocal failed
        if (
            not failed
            and session.activity
            and (session.activity[-1]["type"] == "plan.continuation_requested")
        ):
            failed = True
            raise OSError("claim persistence failed")
        return original_save(session)

    monkeypatch.setattr(manager, "_save_locked", fail_claim_once)
    with pytest.raises(OSError, match="claim persistence failed"):
        manager.claim_plan_continuation(session_id, subject="user")
    current = manager.plan_state(session_id)
    assert current["continuation_pending"] is False
    assert current["continuation_count"] == 0
    durable = SessionRuntimeManager(state_dir).plan_state(session_id)
    assert durable["continuation_pending"] is False
    assert durable["continuation_count"] == 0


def test_continuation_validation_expires_claim_and_reserves_attempt(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    now = [10000.0]
    monkeypatch.setattr("local_shell_mcp.session_runtime.time.time", lambda: now[0])
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    now[0] += PLAN_EXECUTION_LEASE_S + 1
    first = manager.claim_plan_continuation(session_id, subject="user")
    assert first is not None
    now[0] += 5 * 60 + 1
    expired = manager.validate_plan_continuation(session_id, first["claim_id"], subject="user")
    assert expired["valid"] is False
    assert expired["plan"]["continuation_pending"] is False
    assert expired["plan"]["continuation_count"] == 0
    second = manager.claim_plan_continuation(session_id, subject="user")
    assert second is not None
    reserved = manager.validate_plan_continuation(session_id, second["claim_id"], subject="user")
    assert reserved["valid"] is True
    assert reserved["plan"]["continuation_count"] == 1
    assert reserved["plan"]["continuation_reserved"] is True
    durable = SessionRuntimeManager(state_dir).plan_state(session_id)
    assert durable["continuation_count"] == 1
    assert durable["continuation_pending"] is True
    assert durable["continuation_reserved"] is True


def test_continuation_invalidation_rolls_back_when_persistence_fails(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    now = [10000.0]
    monkeypatch.setattr("local_shell_mcp.session_runtime.time.time", lambda: now[0])
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    now[0] += PLAN_EXECUTION_LEASE_S + 1
    claim = manager.claim_plan_continuation(session_id, subject="user")
    assert claim is not None
    before = manager.plan_state(session_id)
    now[0] += 5 * 60 + 1
    original_save = manager._save_locked

    def fail_invalidation(session):
        if session.plan is not None and (not session.plan.continuation_pending):
            raise OSError("invalidation persistence failed")
        return original_save(session)

    monkeypatch.setattr(manager, "_save_locked", fail_invalidation)
    with pytest.raises(OSError, match="invalidation persistence failed"):
        manager.validate_plan_continuation(session_id, claim["claim_id"], subject="user")
    current = manager.plan_state(session_id)
    assert current["continuation_pending"] is True
    assert current["continuation_claim_id"] == before["continuation_claim_id"]
    durable = SessionRuntimeManager(state_dir).plan_state(session_id)
    assert durable["continuation_pending"] is True
    assert durable["continuation_claim_id"] == before["continuation_claim_id"]


def test_expired_continuation_cleanup_persists_when_new_claim_is_ineligible(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    now = [10000.0]
    monkeypatch.setattr("local_shell_mcp.session_runtime.time.time", lambda: now[0])
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    now[0] += PLAN_EXECUTION_LEASE_S + 1
    claim = manager.claim_plan_continuation(session_id, subject="user")
    assert claim is not None
    now[0] += 5 * 60 + 1
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity = now[0]
    manager._save_locked(logical)
    assert manager.claim_plan_continuation(session_id, subject="user") is None
    assert manager.plan_state(session_id)["continuation_pending"] is False
    restored = SessionRuntimeManager(state_dir).plan_state(session_id)
    assert restored["continuation_pending"] is False
    assert restored["continuation_claim_id"] is None


def test_inflight_tool_lease_heartbeat_prevents_age_only_expiry(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    now = [1000.0]
    monkeypatch.setattr("local_shell_mcp.session_runtime.time.time", lambda: now[0])
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    lease = manager.begin_tool_call(session_id, "call-1")
    assert lease is not None
    now[0] += SESSION_IN_FLIGHT_LEASE_S - 1
    assert manager.renew_tool_call(lease) is True
    now[0] += 2
    assert manager._in_flight_count_locked(session_id) == 1
    restored = SessionRuntimeManager(state_dir)
    restored.get(session_id, subject="user")
    assert restored._in_flight_count_locked(session_id) == 1
    now[0] += SESSION_IN_FLIGHT_LEASE_S + 1
    assert manager._in_flight_count_locked(session_id) == 0


@pytest.mark.parametrize("action", ["finish", "cancel"])
def test_session_termination_waits_for_inflight_tool(tmp_path, action):
    manager = SessionRuntimeManager(tmp_path / f".{action}-state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    lease = manager.begin_tool_call(session_id, "call-1", data={"tool": "remote_transfer"})
    with pytest.raises(ValueError, match="tool calls are in flight"):
        manager.manage("user", action=action, session_id=session_id)
    assert manager.finish_tool_call(lease, "tool.completed") is None
    terminal = manager.manage("user", action=action, session_id=session_id)
    assert terminal["status"] == ("completed" if action == "finish" else "cancelled")


def test_continuation_validation_rechecks_agent_activity_and_inflight(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".continuation-state")
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    manager.manage_plan(
        session_id, action="start", objective="Task", steps=[{"id": "work", "text": "Work"}]
    )
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity = time.time() - PLAN_EXECUTION_LEASE_S - 1
    claimed = manager.claim_plan_continuation(session_id, subject="user")
    assert claimed is not None
    claim_id = claimed["claim_id"]
    lease = manager.begin_tool_call(session_id, "call-1", data={"tool": "remote_transfer"})
    validation = manager.validate_plan_continuation(session_id, claim_id, subject="user")
    assert validation["valid"] is False
    assert validation["plan"]["continuation_pending"] is False
    assert manager.finish_tool_call(lease, "tool.completed") is None


@pytest.mark.parametrize("action", ["finish", "cancel"])
def test_terminal_transition_rolls_back_when_activity_persistence_fails(
    tmp_path, monkeypatch, action
):
    state_dir = tmp_path / ".state"
    manager = SessionRuntimeManager(state_dir)
    started = manager.manage("user", action="start", objective="Task")
    session_id = started["session_id"]
    original_append = manager._append_activity_locked

    def fail_terminal_activity(session, event_type, **kwargs):
        if event_type in {"session.completed", "session.cancelled"}:
            raise OSError("simulated terminal activity persistence failure")
        return original_append(session, event_type, **kwargs)

    monkeypatch.setattr(manager, "_append_activity_locked", fail_terminal_activity)
    with pytest.raises(OSError, match="terminal activity persistence failure"):
        manager.manage("user", action=action, session_id=session_id)
    current = manager.manage("user", action="get", session_id=session_id)
    assert current["status"] == "active"
    assert not any(
        event["type"] in {"session.completed", "session.cancelled"}
        for event in current["recent_activity"]
    )
    restored = SessionRuntimeManager(state_dir)
    durable = restored.manage("user", action="get", session_id=session_id)
    assert durable["status"] == "active"


def test_explicit_session_edge_contracts_cover_terminal_and_cleanup_paths(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")

    assert manager.plan_state(None) is None
    assert manager.begin_tool_call(None, "no-session") is None
    assert manager.finish_tool_call(None, "tool.completed") is None
    assert manager.retry_tool_call_cleanup(None) is True
    assert manager.retry_tool_call_cleanup({}) is True
    assert manager.renew_tool_call(None) is False
    assert manager.renew_tool_call({}) is False

    started = manager.manage("user", action="start", objective="Explicit session edges")
    session_id = started["session_id"]
    with pytest.raises(ValueError, match="action=report requires"):
        manager.manage("user", action="report", session_id=session_id)

    reported = manager.manage(
        "user",
        action="report",
        session_id=session_id,
        findings=["", "finding"],
        blockers=["blocker"],
        objective="Updated objective",
        label="Updated label",
    )
    assert reported["objective"] == "Updated objective"
    assert reported["label"] == "Updated label"
    assert reported["progress"]["findings"] == ["finding"]
    assert reported["progress"]["blockers"] == ["blocker"]

    lease = manager.begin_tool_call(session_id, "call-1", data={"tool": "run_shell"})
    assert lease is not None
    with pytest.raises(ValueError, match="while tool calls are in flight"):
        manager.manage("user", action="delete", session_id=session_id)
    assert manager.renew_tool_call({"session_id": session_id, "call_id": "missing"}) is False
    assert manager.finish_tool_call(
        {"session_id": "s_missing", "call_id": "missing"}, "tool.completed"
    ) is None
    assert manager.finish_tool_call(lease, "tool.completed") is None

    cancelled = manager.manage("user", action="cancel", session_id=session_id)
    assert cancelled["status"] == "cancelled"
    with pytest.raises(RuntimeError, match="Logical session is cancelled"):
        manager.begin_tool_call(session_id, "after-cancel")
    with pytest.raises(ValueError, match="Logical session is cancelled"):
        manager.manage("user", action="report", session_id=session_id, summary="too late")
    with pytest.raises(ValueError, match="Logical session is cancelled"):
        manager.manage_plan(
            session_id,
            action="start",
            objective="Too late",
            steps=[{"id": "x", "text": "x"}],
        )
    assert manager.manage("user", action="delete", session_id=session_id) == {
        "session_id": session_id,
        "deleted": True,
    }


def test_tool_lease_renew_and_cleanup_restore_state_on_persistence_failure(
    tmp_path, monkeypatch
):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start", objective="Lease rollback")["session_id"]
    lease = manager.begin_tool_call(session_id, "call-rollback")
    assert lease is not None

    logical = manager._sessions[session_id]
    previous = logical.in_flight_calls["call-rollback"]["heartbeat_at"]
    original_save = manager._save_locked

    def fail_save(_session):
        raise OSError("lease persistence failed")

    monkeypatch.setattr(manager, "_save_locked", fail_save)
    with pytest.raises(OSError, match="lease persistence failed"):
        manager.renew_tool_call(lease)
    assert logical.in_flight_calls["call-rollback"]["heartbeat_at"] == previous

    with pytest.raises(OSError, match="lease persistence failed"):
        manager.retry_tool_call_cleanup(lease)
    assert "call-rollback" in manager._sessions[session_id].in_flight_calls

    monkeypatch.setattr(manager, "_save_locked", original_save)
    assert manager.retry_tool_call_cleanup(lease) is True
    assert "call-rollback" not in manager._sessions[session_id].in_flight_calls


def test_continuation_abandon_and_unreserved_report_edges(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start", objective="Continuation edges")[
        "session_id"
    ]
    manager.manage_plan(
        session_id,
        action="start",
        objective="Continuation edges",
        steps=[{"id": "work", "text": "Work"}],
    )
    plan = manager._sessions[session_id].plan
    assert plan is not None
    plan.last_agent_activity -= PLAN_EXECUTION_LEASE_S + 1

    claim = manager.claim_plan_continuation(session_id, claim_id="c_abandon")
    assert claim is not None
    assert manager.abandon_plan_continuation(session_id, None) is False
    assert manager.abandon_plan_continuation(session_id, "wrong") is False
    assert manager.abandon_plan_continuation(session_id, "c_abandon") is True
    assert manager.plan_state(session_id)["continuation_pending"] is False

    claim = manager.claim_plan_continuation(session_id, claim_id="c_unreserved")
    assert claim is not None
    with pytest.raises(ValueError, match="claim is stale"):
        manager.report_plan_continuation(
            session_id, accepted=False, claim_id="wrong-claim"
        )
    with pytest.raises(ValueError, match="not reserved"):
        manager.report_plan_continuation(
            session_id, accepted=True, claim_id="c_unreserved"
        )
    assert manager.abandon_plan_continuation(session_id, "c_unreserved") is True


def test_idle_session_becomes_stale_and_can_resume(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start", objective="Forgotten task")["session_id"]
    logical = manager._sessions[session_id]
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)

    state = manager.get(session_id, subject="user")
    assert state["status"] == "stale"
    assert state["recent_activity"][-1]["type"] == "session.stale"
    assert state["recent_activity"][-1]["actor"] == "system"
    assert manager.manage("user", action="get", session_id=session_id)["status"] == "stale"
    assert [entry["type"] for entry in manager.get(session_id)["recent_activity"]].count("session.stale") == 1
    assert SessionRuntimeManager(tmp_path / ".state").get(session_id)["status"] == "stale"
    assert manager.manage("user", action="resume", session_id=session_id)["status"] == "active"


def test_stale_transition_ignores_independent_workloads_and_protects_tool_calls(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start")["session_id"]
    lease = manager.begin_tool_call(session_id, "running-call", subject="user")
    logical = manager._sessions[session_id]
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)
    assert manager.list_sessions(subject="user")[0]["status"] == "active"
    manager.finish_tool_call(lease, "tool.completed")
    manager._sessions[session_id].updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(manager._sessions[session_id])
    # Persistent Job/Shell state is never consulted by Logical Session expiry.
    assert manager.list_sessions(subject="user")[0]["status"] == "stale"


def test_stale_history_competes_with_other_terminal_sessions_by_age(tmp_path, monkeypatch):
    monkeypatch.setattr("local_shell_mcp.session_runtime.SESSION_HISTORY_LIMIT_PER_PRINCIPAL", 3)
    manager = SessionRuntimeManager(tmp_path / ".state")
    oldest = manager.manage("user", action="start")["session_id"]
    manager.manage("user", action="finish", session_id=oldest)
    idle = manager.manage("user", action="start")["session_id"]
    manager._sessions[idle].updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(manager._sessions[idle])
    newer = manager.manage("user", action="start")["session_id"]
    manager.manage("user", action="cancel", session_id=newer)

    current = manager.manage("user", action="start")["session_id"]
    with pytest.raises(ValueError, match="Unknown logical session"):
        manager.get(oldest)
    assert manager.get(idle)["status"] == "stale"
    assert manager.get(newer)["status"] == "cancelled"
    manager.manage("user", action="start")
    with pytest.raises(ValueError, match="Unknown logical session"):
        manager.get(idle)
    assert manager.get(newer)["status"] == "cancelled"
    assert manager.get(current)["status"] == "active"


def test_stale_plan_does_not_auto_continue(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start")["session_id"]
    manager.manage_plan(session_id, action="start", objective="Plan", steps=[{"id": "a", "text": "A"}])
    manager._sessions[session_id].updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(manager._sessions[session_id])
    assert manager.get(session_id)["status"] == "stale"
    assert manager.plan_state(session_id)["continuation_due"] is False
    assert manager.claim_plan_continuation(session_id) is None
    assert manager.manage("user", action="resume", session_id=session_id)["status"] == "active"


@pytest.mark.parametrize("action", ["report", "finish", "cancel"])
def test_expired_session_requires_resume_before_mutation(tmp_path, action):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start", objective="Old task")["session_id"]
    logical = manager._sessions[session_id]
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)

    kwargs = {"summary": "This must not revive the session"} if action == "report" else {}
    with pytest.raises(ValueError, match="Logical session is stale"):
        manager.manage("user", action=action, session_id=session_id, **kwargs)
    state = manager.get(session_id, subject="user")
    assert state["status"] == "stale"
    assert state["progress"]["summary"] is None


def test_expired_session_can_be_deleted_or_resumed_without_prior_get(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    expired = manager.manage("user", action="start")["session_id"]
    logical = manager._sessions[expired]
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)
    assert manager.manage("user", action="delete", session_id=expired)["deleted"] is True
    with pytest.raises(ValueError, match="Unknown logical session"):
        manager.get(expired)

    resumed = manager.manage("user", action="start")["session_id"]
    logical = manager._sessions[resumed]
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)
    state = manager.manage("user", action="resume", session_id=resumed)
    assert state["status"] == "active"
    assert [event["type"] for event in state["recent_activity"][-2:]] == [
        "session.stale", "session.resumed"
    ]


def test_expired_session_plan_get_reports_no_goal_or_continuation(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start")["session_id"]
    manager.manage_plan(session_id, action="start", objective="Work", steps=[{"id": "one", "text": "Do it"}])
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity -= SESSION_STALE_AFTER_S + 1
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)

    state = manager.manage_plan(session_id, action="get", subject="user")
    assert state["goal_mode"] is False
    assert state["plan"]["status"] == "active"
    assert state["plan"]["continuation_due"] is False
    assert manager.get(session_id)["status"] == "stale"
    assert manager.plan_state(session_id)["continuation_due"] is False


def test_plan_state_expires_idle_session_without_another_access(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start")["session_id"]
    manager.manage_plan(session_id, action="start", objective="Work", steps=[{"id": "one", "text": "Do it"}])
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity -= SESSION_STALE_AFTER_S + 1
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)
    assert manager.plan_state(session_id)["continuation_due"] is False
    assert manager.get(session_id)["status"] == "stale"


def test_session_listing_survives_best_effort_prune_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("local_shell_mcp.session_runtime.SESSION_HISTORY_LIMIT_PER_PRINCIPAL", 2)
    manager = SessionRuntimeManager(tmp_path / ".state")
    first = manager.manage("user", action="start")["session_id"]
    second = manager.manage("user", action="start")["session_id"]
    third = manager.manage("user", action="start")["session_id"]
    manager.manage("user", action="finish", session_id=first)
    store = manager._state_store()

    def unavailable_delete(key):
        raise OSError("temporary storage failure")

    monkeypatch.setattr(store, "delete", unavailable_delete)
    monkeypatch.setattr(manager, "_state_store", lambda: store)
    listed = manager.list_sessions(subject="user")
    assert {item["session_id"] for item in listed} == {first, second, third}
    assert manager.get(second)["status"] == "active"


def test_continuation_validation_rechecks_session_expiry(tmp_path):
    manager = SessionRuntimeManager(tmp_path / ".state")
    session_id = manager.manage("user", action="start")["session_id"]
    manager.manage_plan(session_id, action="start", objective="Work", steps=[{"id": "one", "text": "Do it"}])
    logical = manager._sessions[session_id]
    assert logical.plan is not None
    logical.plan.last_agent_activity -= PLAN_EXECUTION_LEASE_S + 1
    manager._save_locked(logical)
    claimed = manager.claim_plan_continuation(session_id)
    assert claimed is not None
    logical.updated_at -= SESSION_STALE_AFTER_S + 1
    manager._save_locked(logical)

    result = manager.validate_plan_continuation(session_id, claimed["claim_id"])
    assert result["valid"] is False
    assert result["plan"]["continuation_due"] is False
    assert manager.get(session_id)["status"] == "stale"
