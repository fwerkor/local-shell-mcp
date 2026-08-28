from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from local_shell_mcp import chat_dispatch_bridge, tools


class FakeStore:
    jobs = {}
    cancelled = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def enqueue(self, **kwargs):
        job = SimpleNamespace(
            dispatch_id="chat_1",
            state="QUEUED",
            prompt_text=kwargs["prompt"],
            kwargs=kwargs,
        )
        self.jobs[job.dispatch_id] = job
        return job

    def cancel(self, dispatch_id):
        self.cancelled.append(dispatch_id)
        job = self.jobs.setdefault(
            dispatch_id,
            SimpleNamespace(dispatch_id=dispatch_id, state="CANCELLED", prompt_text=""),
        )
        job.state = "CANCELLED"
        return job


class FakeBackend:
    ChatDispatchStore = FakeStore
    TERMINAL_JOB_STATES = {"ACKNOWLEDGED", "FAILED", "CANCELLED"}
    ensure_calls = []
    status_calls = []

    @staticmethod
    def job_payload(job):
        return {"dispatch_id": job.dispatch_id, "state": job.state}

    @classmethod
    def ensure_chat_dispatch_worker(cls, **kwargs):
        cls.ensure_calls.append(kwargs)
        return {"started": True, "pid": 123}

    @classmethod
    def chat_dispatch_status(cls, **kwargs):
        cls.status_calls.append(kwargs)
        return {"jobs": [], "pages": [], "pending": 0, "lease": None}


class ChatDispatchBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "lws"
        self.root.mkdir()
        FakeStore.jobs = {}
        FakeStore.cancelled = []
        FakeBackend.ensure_calls = []
        FakeBackend.status_calls = []
        self.load_patch = patch.object(
            chat_dispatch_bridge,
            "_load_backend",
            return_value=(self.root, FakeBackend),
        )
        self.load_mock = self.load_patch.start()
        self.watchdog_ensure_patch = patch.object(
            chat_dispatch_bridge,
            "ensure_chat_dispatch_watchdog",
            return_value={"started": False, "status": "running", "alive": True},
        )
        self.watchdog_inspect_patch = patch.object(
            chat_dispatch_bridge,
            "inspect_chat_dispatch_watchdog",
            return_value={"status": "running", "alive": True},
        )
        self.watchdog_stop_patch = patch.object(
            chat_dispatch_bridge,
            "stop_chat_dispatch_watchdog",
            return_value={"requested": True, "status": "stopped", "alive": False},
        )
        self.watchdog_ensure_patch.start()
        self.watchdog_inspect_patch.start()
        self.watchdog_stop_patch.start()
        self.settings = SimpleNamespace(
            workspace_root=Path(self.tmp.name),
            chat_dispatch_lws_repo=None,
            chat_dispatch_max_windows=4,
            chat_dispatch_idle_close_s=90,
            chat_dispatch_watchdog_enabled=True,
            chat_dispatch_watchdog_interval_s=15,
        )

    def tearDown(self):
        self.watchdog_stop_patch.stop()
        self.watchdog_inspect_patch.stop()
        self.watchdog_ensure_patch.stop()
        self.load_patch.stop()
        self.tmp.cleanup()

    def test_enqueue_forwards_durable_identity_and_starts_worker(self):
        result = chat_dispatch_bridge.manage_chat_dispatch(
            self.settings,
            action="enqueue",
            prompt="do the child work",
            conversation_key="child-a",
            project_url="https://chatgpt.com/g/project",
            idempotency_key="request-42",
            max_windows=3,
            idle_close_s=45,
        )
        self.assertEqual(result["dispatch"]["dispatch_id"], "chat_1")
        job = FakeStore.jobs["chat_1"]
        self.assertEqual(job.kwargs["dispatch_key"], "request-42")
        self.assertEqual(job.kwargs["conversation_key"], "child-a")
        self.assertEqual(job.kwargs["max_windows"], 3)
        self.assertEqual(job.kwargs["idle_close_s"], 45)
        self.assertEqual(FakeBackend.ensure_calls[-1]["repo_root"], self.root)
        self.assertEqual(result["watchdog"]["status"], "running")

    def test_enqueue_requires_idempotency_key_before_loading_backend(self):
        with self.assertRaisesRegex(ValueError, "idempotency_key is required"):
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings,
                action="enqueue",
                prompt="do work",
                conversation_url="https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            )

    def test_new_conversation_requires_stable_conversation_key(self):
        with self.assertRaisesRegex(ValueError, "conversation_key is required"):
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings,
                action="enqueue",
                prompt="do work",
                project_url="https://chatgpt.com/g/project",
                idempotency_key="request-1",
            )

    def test_enqueue_rejects_ambiguous_existing_and_new_targets(self):
        with self.assertRaisesRegex(ValueError, "not both"):
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings,
                action="enqueue",
                prompt="do work",
                conversation_key="child-a",
                conversation_url="https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                project_url="https://chatgpt.com/g/project",
                idempotency_key="request-1",
            )

    def test_status_limit_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "limit must be between"):
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings, action="status", limit=501
            )

    def test_action_and_runtime_bounds_are_validated(self):
        with self.assertRaisesRegex(ValueError, "action must be one of"):
            chat_dispatch_bridge.manage_chat_dispatch(self.settings, action="unknown")
        with self.assertRaisesRegex(ValueError, "max_windows must be between"):
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings, action="status", max_windows=0
            )
        with self.assertRaisesRegex(ValueError, "idle_close_s must be between"):
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings, action="status", idle_close_s=0
            )

    def test_enqueue_requires_nonempty_prompt_after_target_validation(self):
        with self.assertRaisesRegex(ValueError, "prompt is required"):
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings,
                action="enqueue",
                prompt="",
                conversation_url="https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                idempotency_key="request-empty",
            )

    def test_cancel_requires_dispatch_id(self):
        with self.assertRaisesRegex(ValueError, "dispatch_id is required"):
            chat_dispatch_bridge.manage_chat_dispatch(self.settings, action="cancel")

    def test_ensure_starts_worker_and_resident_watchdog(self):
        result = chat_dispatch_bridge.manage_chat_dispatch(
            self.settings, action="ensure", limit=9
        )

        self.assertTrue(result["worker"]["started"])
        self.assertEqual(result["watchdog"]["status"], "running")
        self.assertEqual(FakeBackend.status_calls[-1], {"dispatch_id": None, "limit": 9})

    def test_watchdog_can_be_disabled_for_enqueue_and_ensure(self):
        self.settings.chat_dispatch_watchdog_enabled = False

        enqueue = chat_dispatch_bridge.manage_chat_dispatch(
            self.settings,
            action="enqueue",
            prompt="work",
            conversation_url="https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            idempotency_key="request-disabled",
        )
        ensured = chat_dispatch_bridge.manage_chat_dispatch(self.settings, action="ensure")

        self.assertEqual(enqueue["watchdog"]["status"], "disabled")
        self.assertEqual(ensured["watchdog"]["status"], "disabled")

    def test_status_does_not_start_worker(self):
        result = chat_dispatch_bridge.manage_chat_dispatch(
            self.settings, action="status", dispatch_id="chat_1", limit=7
        )
        self.assertEqual(result["action"], "status")
        self.assertEqual(FakeBackend.ensure_calls, [])
        self.assertEqual(
            FakeBackend.status_calls[-1], {"dispatch_id": "chat_1", "limit": 7}
        )
        self.assertEqual(result["watchdog"]["status"], "running")

    def test_watchdog_status_and_stop_do_not_load_backend_but_start_validates_it(self):
        self.assertEqual(
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings, action="watchdog_status"
            )["watchdog"]["status"],
            "running",
        )
        self.assertEqual(
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings, action="watchdog_stop"
            )["watchdog"]["status"],
            "stopped",
        )
        self.assertEqual(self.load_mock.call_count, 0)
        self.assertEqual(
            chat_dispatch_bridge.manage_chat_dispatch(
                self.settings, action="watchdog_start"
            )["watchdog"]["status"],
            "running",
        )
        self.assertEqual(self.load_mock.call_count, 1)

    def test_cancel_is_followed_by_worker_ensure_for_page_cleanup(self):
        FakeStore.jobs["chat_1"] = SimpleNamespace(
            dispatch_id="chat_1", state="QUEUED", prompt_text="x"
        )
        result = chat_dispatch_bridge.manage_chat_dispatch(
            self.settings, action="cancel", dispatch_id="chat_1"
        )
        self.assertEqual(result["dispatch"]["state"], "CANCELLED")
        self.assertEqual(FakeStore.cancelled, ["chat_1"])
        self.assertEqual(len(FakeBackend.ensure_calls), 1)

    def test_prompt_is_redacted_from_tool_audit_arguments(self):
        safe = tools._safe_audit_call_arguments(
            "chat_dispatch",
            {"action": "enqueue", "prompt": "非常敏感的子任务提示", "conversation_key": "c"},
        )
        self.assertTrue(safe["prompt"].startswith("<redacted:"))
        self.assertNotIn("敏感", safe["prompt"])
        self.assertEqual(safe["conversation_key"], "c")

    def test_chat_dispatch_is_model_visible_with_open_world_mutation_annotations(self):
        async def listed():
            return {tool.name: tool for tool in await tools.build_mcp().list_tools()}

        with patch.dict(
            os.environ,
            {"LOCAL_SHELL_MCP_WORKSPACE_ROOT": self.tmp.name},
        ):
            tools.get_settings.cache_clear()
            try:
                visible = asyncio.run(listed())
            finally:
                tools.get_settings.cache_clear()
        self.assertIn("chat_dispatch", visible)
        tool = visible["chat_dispatch"]
        self.assertTrue(tool.annotations.openWorldHint)
        self.assertFalse(tool.annotations.readOnlyHint)
        self.assertTrue(tool.annotations.destructiveHint)
        for name in (
            "action",
            "prompt",
            "conversation_key",
            "conversation_url",
            "project_url",
            "dispatch_id",
            "idempotency_key",
            "max_windows",
            "idle_close_s",
            "limit",
        ):
            self.assertIn(name, tool.inputSchema["properties"])


class ChatDispatchBackendContractTests(unittest.TestCase):
    def test_path_fence_accepts_equivalent_root_alias(self):
        configured_root = Path("configured-root")
        module_path = Path("resolved-root") / "src" / "lws" / "chat_dispatch.py"

        def samefile(candidate, expected):
            return Path(candidate).name == "resolved-root" and Path(expected) == configured_root

        with patch.object(chat_dispatch_bridge.os.path, "samefile", side_effect=samefile):
            self.assertTrue(
                chat_dispatch_bridge._is_path_within_root(module_path, configured_root)
            )

    def test_resolve_backend_uses_configured_or_workspace_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            configured = workspace / "configured"
            default = workspace / "tools" / "localshell-web-supervisor"
            for root in (configured, default):
                backend = root / "src" / "lws" / "chat_dispatch.py"
                backend.parent.mkdir(parents=True)
                backend.write_text("# fixture\n", encoding="utf-8")

            resolved = chat_dispatch_bridge._resolve_lws_repo(
                SimpleNamespace(
                    workspace_root=workspace,
                    chat_dispatch_lws_repo=str(configured),
                )
            )
            fallback = chat_dispatch_bridge._resolve_lws_repo(
                SimpleNamespace(workspace_root=workspace, chat_dispatch_lws_repo=None)
            )

            self.assertEqual(resolved, configured.resolve())
            self.assertEqual(fallback, default.resolve())

    def test_resolve_backend_reports_all_missing_candidates(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(RuntimeError, "Checked:"),
        ):
            chat_dispatch_bridge._resolve_lws_repo(
                SimpleNamespace(workspace_root=Path(tmp), chat_dispatch_lws_repo=None)
            )

    def test_backend_loaded_from_different_checkout_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "expected"
            module = SimpleNamespace(__file__=str(Path(tmp) / "other" / "chat_dispatch.py"))
            old_cache = chat_dispatch_bridge._BACKEND_CACHE
            chat_dispatch_bridge._BACKEND_CACHE = None
            try:
                with (
                    patch.object(chat_dispatch_bridge, "_resolve_lws_repo", return_value=root),
                    patch.object(chat_dispatch_bridge.importlib, "import_module", return_value=module),
                    self.assertRaisesRegex(RuntimeError, "unexpected path"),
                ):
                    chat_dispatch_bridge._load_backend(SimpleNamespace())
            finally:
                chat_dispatch_bridge._BACKEND_CACHE = old_cache

    def test_incompatible_backend_fails_with_missing_api_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = SimpleNamespace(__file__=str(root / "src" / "lws" / "chat_dispatch.py"))
            old_cache = chat_dispatch_bridge._BACKEND_CACHE
            chat_dispatch_bridge._BACKEND_CACHE = None
            try:
                with (
                    patch.object(chat_dispatch_bridge, "_resolve_lws_repo", return_value=root),
                    patch.object(chat_dispatch_bridge.importlib, "import_module", return_value=module),
                    self.assertRaisesRegex(RuntimeError, "missing API: ChatDispatchStore"),
                ):
                    chat_dispatch_bridge._load_backend(SimpleNamespace())
            finally:
                chat_dispatch_bridge._BACKEND_CACHE = old_cache


if __name__ == "__main__":
    unittest.main()
