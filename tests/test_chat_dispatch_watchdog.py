from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_shell_mcp import chat_dispatch_bridge
from local_shell_mcp import chat_dispatch_watchdog as watchdog


class ChatDispatchWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(
            state_backend="file",
            stateless_controller=False,
            state_dir=Path(self.tmp.name),
            chat_dispatch_watchdog_interval_s=15,
        )
        self.lock_patch = patch.object(
            watchdog,
            "state_lock",
            side_effect=lambda _key: contextlib.nullcontext(),
        )
        self.lock_patch.start()

    def tearDown(self):
        self.lock_patch.stop()
        self.tmp.cleanup()

    def write_state(self, **updates):
        state = {
            "owner_id": "owner-1",
            "pid": 111,
            "status": "running",
            "started_at": 10.0,
            "heartbeat_at": 100.0,
            "interval_s": 10,
            "stop_requested": False,
            "last_ensure_at": None,
            "last_error": None,
        }
        state.update(updates)
        watchdog._write_state_unlocked(self.settings, state)
        return state

    @patch.object(watchdog, "pid_exists", return_value=True)
    def test_inspect_classifies_stale_live_watchdog(self, _pid_exists):
        self.write_state()

        status = watchdog.inspect_chat_dispatch_watchdog(self.settings, now=131)

        self.assertEqual(status["status"], "stale_live")
        self.assertTrue(status["alive"])
        self.assertEqual(status["heartbeat_age_s"], 31)

    @patch.object(watchdog, "pid_exists", return_value=False)
    def test_inspect_preserves_recent_starting_reservation(self, _pid_exists):
        self.write_state(status="starting", started_at=100.0)

        status = watchdog.inspect_chat_dispatch_watchdog(self.settings, now=104.0)

        self.assertEqual(status["status"], "starting")

    def test_pid_exists_handles_posix_process_states(self):
        with (
            patch.object(watchdog.os, "name", "posix"),
            patch.object(watchdog.os, "kill") as kill,
        ):
            self.assertFalse(watchdog.pid_exists(0))
            self.assertTrue(watchdog.pid_exists(123))
            kill.assert_called_once_with(123, 0)

        with (
            patch.object(watchdog.os, "name", "posix"),
            patch.object(watchdog.os, "kill", side_effect=ProcessLookupError),
        ):
            self.assertFalse(watchdog.pid_exists(123))

        with (
            patch.object(watchdog.os, "name", "posix"),
            patch.object(watchdog.os, "kill", side_effect=PermissionError),
        ):
            self.assertTrue(watchdog.pid_exists(123))

    def test_pid_exists_handles_windows_process_handles(self):
        kernel32 = SimpleNamespace(
            OpenProcess=Mock(side_effect=[0, 456]),
            CloseHandle=Mock(),
        )
        with (
            patch.object(watchdog.os, "name", "nt"),
            patch.object(
                watchdog.ctypes,
                "windll",
                SimpleNamespace(kernel32=kernel32),
                create=True,
            ),
        ):
            self.assertFalse(watchdog.pid_exists(123))
            self.assertTrue(watchdog.pid_exists(123))

        kernel32.CloseHandle.assert_called_once_with(456)

    def test_inspect_and_stop_are_idempotent_without_state(self):
        inspected = watchdog.inspect_chat_dispatch_watchdog(self.settings)
        stopped = watchdog.stop_chat_dispatch_watchdog(self.settings)

        self.assertEqual(inspected["status"], "stopped")
        self.assertFalse(inspected["alive"])
        self.assertFalse(stopped["requested"])

    def test_malformed_state_is_treated_as_absent(self):
        watchdog._state_path(self.settings).write_text("{broken", encoding="utf-8")

        self.assertIsNone(watchdog._read_state_unlocked(self.settings))
        self.assertEqual(
            watchdog.inspect_chat_dispatch_watchdog(self.settings)["status"],
            "stopped",
        )

    @patch.object(watchdog, "pid_exists", return_value=False)
    def test_inspect_classifies_dead_watchdog(self, _pid_exists):
        self.write_state()

        status = watchdog.inspect_chat_dispatch_watchdog(self.settings, now=101)

        self.assertEqual(status["status"], "dead")
        self.assertFalse(status["alive"])

    @patch.object(watchdog.subprocess, "Popen")
    @patch.object(watchdog, "pid_exists", return_value=True)
    def test_ensure_reuses_existing_live_watchdog(self, _pid_exists, popen):
        self.write_state()

        status = watchdog.ensure_chat_dispatch_watchdog(self.settings)

        self.assertFalse(status["started"])
        self.assertEqual(status["pid"], 111)
        popen.assert_not_called()

    @patch.object(watchdog, "pid_exists", return_value=True)
    @patch.object(watchdog.subprocess, "Popen")
    def test_ensure_restarts_terminal_state_even_if_pid_was_reused(self, popen, _pid_exists):
        self.write_state(status="stopped")
        popen.return_value = SimpleNamespace(pid=222)

        with patch.object(
            watchdog,
            "inspect_chat_dispatch_watchdog",
            return_value={"status": "running", "alive": True},
        ):
            status = watchdog.ensure_chat_dispatch_watchdog(self.settings)

        self.assertTrue(status["started"])
        popen.assert_called_once()

    @patch.object(watchdog, "pid_exists", return_value=False)
    @patch.object(watchdog.subprocess, "Popen")
    def test_ensure_launches_detached_process_and_writes_reservation(self, popen, _pid_exists):
        self.settings.chat_dispatch_lws_repo = "configured-lws"
        popen.return_value = SimpleNamespace(pid=222)

        with patch.object(
            watchdog,
            "inspect_chat_dispatch_watchdog",
            return_value={"status": "running", "alive": True},
        ):
            status = watchdog.ensure_chat_dispatch_watchdog(self.settings, interval_s=20)

        self.assertTrue(status["started"])
        saved = watchdog._read_state_unlocked(self.settings)
        self.assertEqual(saved["pid"], 222)
        self.assertEqual(saved["interval_s"], 20)
        command = popen.call_args.args[0]
        self.assertIn("local_shell_mcp.chat_dispatch_watchdog", command)
        self.assertEqual(command[-1], "20")
        child_env = popen.call_args.kwargs["env"]
        self.assertEqual(
            child_env["LOCAL_SHELL_MCP_CHAT_DISPATCH_LWS_REPO"],
            "configured-lws",
        )
        self.assertEqual(
            child_env["LOCAL_SHELL_MCP_STATE_DIR"],
            str(Path(self.tmp.name).resolve()),
        )
        self.assertEqual(child_env["LOCAL_SHELL_MCP_CHAT_DISPATCH_WATCHDOG_INTERVAL_S"], "20")
        if os.name == "nt":
            self.assertTrue(popen.call_args.kwargs["creationflags"] & 0x08000000)

    @patch.object(watchdog, "pid_exists", return_value=False)
    @patch.object(watchdog.subprocess, "Popen")
    def test_ensure_waits_for_worker_handoff(self, popen, _pid_exists):
        popen.return_value = SimpleNamespace(pid=222)
        starting = {"status": "starting", "alive": True}
        running = {"status": "running", "alive": True}

        with (
            patch.object(
                watchdog,
                "inspect_chat_dispatch_watchdog",
                side_effect=[starting, running],
            ),
            patch.object(watchdog.time, "sleep") as sleep,
        ):
            status = watchdog.ensure_chat_dispatch_watchdog(self.settings)

        self.assertTrue(status["started"])
        self.assertEqual(status["status"], "running")
        sleep.assert_called_once_with(0.05)

    def test_claim_replaces_transient_launcher_pid_with_worker_pid(self):
        self.write_state(owner_id="owner-handoff", pid=111, status="starting")

        claimed = watchdog._claim_watchdog(self.settings, "owner-handoff")

        self.assertTrue(claimed)
        saved = watchdog._read_state_unlocked(self.settings)
        self.assertEqual(saved["pid"], os.getpid())
        self.assertEqual(saved["status"], "running")

    def test_claim_times_out_when_reservation_owner_does_not_match(self):
        self.write_state(owner_id="other-owner", status="starting")

        with (
            patch.object(watchdog.time, "time", side_effect=[0.0, 0.0, 6.0]),
            patch.object(watchdog.time, "sleep") as sleep,
        ):
            claimed = watchdog._claim_watchdog(self.settings, "expected-owner")

        self.assertFalse(claimed)
        sleep.assert_called_once_with(0.05)

    @patch.object(watchdog, "pid_exists", return_value=True)
    def test_stop_requests_cooperative_exit_without_killing_process(self, _pid_exists):
        self.write_state()

        status = watchdog.stop_chat_dispatch_watchdog(self.settings, wait_s=0)

        self.assertTrue(status["requested"])
        self.assertEqual(status["status"], "stopping")
        self.assertTrue(watchdog._read_state_unlocked(self.settings)["stop_requested"])

    @patch.object(watchdog, "pid_exists", return_value=True)
    def test_stop_waits_until_worker_exits(self, _pid_exists):
        self.write_state()
        stopping = {"status": "stopping", "alive": True}
        stopped = {"status": "stopped", "alive": False}

        with (
            patch.object(
                watchdog,
                "inspect_chat_dispatch_watchdog",
                side_effect=[stopping, stopped],
            ),
            patch.object(watchdog.time, "sleep") as sleep,
        ):
            status = watchdog.stop_chat_dispatch_watchdog(self.settings, wait_s=1)

        self.assertTrue(status["requested"])
        self.assertEqual(status["status"], "stopped")
        sleep.assert_called_once_with(0.05)

    def test_non_file_state_backend_is_rejected(self):
        self.settings.state_backend = "redis"

        with self.assertRaisesRegex(RuntimeError, "local file state backend"):
            watchdog.ensure_chat_dispatch_watchdog(self.settings)

    def test_stateless_controller_is_rejected(self):
        self.settings.stateless_controller = True

        with self.assertRaisesRegex(RuntimeError, "stateless controller"):
            watchdog.ensure_chat_dispatch_watchdog(self.settings)

    def test_interval_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "between 2 and 3600"):
            watchdog._bounded_interval(1)
        with self.assertRaisesRegex(ValueError, "between 2 and 3600"):
            watchdog._bounded_interval(3601)

    def test_worker_reconciles_pending_queue_then_stops_cooperatively(self):
        owner_id = "owner-run"
        self.write_state(
            owner_id=owner_id,
            pid=os.getpid(),
            status="starting",
            interval_s=2,
        )
        calls = []

        def manage(_settings, *, action, **_kwargs):
            calls.append(action)
            return {"pending": 1} if action == "status" else {"worker": {"started": True}}

        def request_stop(_seconds):
            state = watchdog._read_state_unlocked(self.settings)
            state["stop_requested"] = True
            watchdog._write_state_unlocked(self.settings, state)

        with (
            patch.object(chat_dispatch_bridge, "manage_chat_dispatch", side_effect=manage),
            patch.object(watchdog.time, "sleep", side_effect=request_stop),
        ):
            code = watchdog.run_chat_dispatch_watchdog(
                self.settings,
                owner_id=owner_id,
                interval_s=2,
            )

        self.assertEqual(code, 0)
        self.assertEqual(calls, ["status", "ensure"])
        self.assertEqual(watchdog._read_state_unlocked(self.settings)["status"], "stopped")

    def test_worker_records_dispatch_error_before_cooperative_stop(self):
        owner_id = "owner-error"
        self.write_state(
            owner_id=owner_id,
            pid=os.getpid(),
            status="starting",
            interval_s=2,
        )

        def request_stop(_seconds):
            state = watchdog._read_state_unlocked(self.settings)
            state["stop_requested"] = True
            watchdog._write_state_unlocked(self.settings, state)

        with (
            patch.object(
                chat_dispatch_bridge,
                "manage_chat_dispatch",
                side_effect=RuntimeError("backend unavailable"),
            ),
            patch.object(watchdog.time, "sleep", side_effect=request_stop),
        ):
            code = watchdog.run_chat_dispatch_watchdog(
                self.settings,
                owner_id=owner_id,
                interval_s=2,
            )

        self.assertEqual(code, 0)
        state = watchdog._read_state_unlocked(self.settings)
        self.assertEqual(state["status"], "stopped")
        self.assertIn("backend unavailable", state["last_error"])

    @patch.object(watchdog, "_claim_watchdog", return_value=False)
    def test_worker_exits_when_reservation_cannot_be_claimed(self, _claim):
        self.assertEqual(
            watchdog.run_chat_dispatch_watchdog(
                self.settings,
                owner_id="missing",
                interval_s=2,
            ),
            3,
        )

    @patch.object(watchdog, "_claim_watchdog", return_value=True)
    def test_worker_exits_when_owner_generation_changes(self, _claim):
        self.write_state(owner_id="new-owner", pid=os.getpid())

        code = watchdog.run_chat_dispatch_watchdog(
            self.settings,
            owner_id="old-owner",
            interval_s=2,
        )

        self.assertEqual(code, 4)
        self.assertEqual(watchdog._read_state_unlocked(self.settings)["owner_id"], "new-owner")

    def test_worker_honors_stop_requested_before_dispatch(self):
        owner_id = "owner-stopped"
        self.write_state(
            owner_id=owner_id,
            pid=os.getpid(),
            status="starting",
            stop_requested=True,
        )

        code = watchdog.run_chat_dispatch_watchdog(
            self.settings,
            owner_id=owner_id,
            interval_s=2,
        )

        self.assertEqual(code, 0)
        self.assertEqual(watchdog._read_state_unlocked(self.settings)["status"], "stopped")

    def test_worker_exits_if_owner_changes_during_dispatch(self):
        owner_id = "owner-dispatch"
        self.write_state(owner_id=owner_id, pid=os.getpid(), status="starting")

        def change_owner(_settings, *, action, **_kwargs):
            self.assertEqual(action, "status")
            state = watchdog._read_state_unlocked(self.settings)
            state["owner_id"] = "replacement-owner"
            watchdog._write_state_unlocked(self.settings, state)
            return {"pending": 0}

        with patch.object(chat_dispatch_bridge, "manage_chat_dispatch", side_effect=change_owner):
            code = watchdog.run_chat_dispatch_watchdog(
                self.settings,
                owner_id=owner_id,
                interval_s=2,
            )

        self.assertEqual(code, 4)
        self.assertEqual(
            watchdog._read_state_unlocked(self.settings)["owner_id"],
            "replacement-owner",
        )

    def test_main_forwards_owner_and_interval(self):
        with (
            patch.object(watchdog, "get_settings", return_value=self.settings),
            patch.object(watchdog, "run_chat_dispatch_watchdog", return_value=7) as run,
        ):
            code = watchdog.main(
                ["--run", "--owner-id", "owner-main", "--interval", "25"]
            )

        self.assertEqual(code, 7)
        run.assert_called_once_with(
            self.settings,
            owner_id="owner-main",
            interval_s=25,
        )


if __name__ == "__main__":
    unittest.main()
