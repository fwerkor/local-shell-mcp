"""User-owned tool approval preferences, independent of authorization grants."""
from __future__ import annotations

from .approval_runtime import approval_policy_decision, ask_user_approval_policy

MODES = ("automatic", "dangerous", "all")
GLOBAL_KEY = "approval.mode"
CHAT_PREFIX = "approval.conversation."


def validate_mode(value, *, inherit=False):
    if inherit and value == "inherit":
        return value
    if not isinstance(value, str) or value not in MODES:
        raise ValueError("Invalid approval mode")
    return value


def effective_mode(repo, owner, conversation_id, agent=None, *, parent_mode=None):
    chat = repo.setting(owner, CHAT_PREFIX + conversation_id, "inherit")
    mode = chat if chat in MODES else (agent or {}).get("approval_mode", "inherit")
    if mode not in MODES:
        mode = repo.setting(owner, GLOBAL_KEY, "automatic")
    mode = mode if mode in MODES else "automatic"
    # A delegated agent may tighten, but cannot weaken its parent's policy.
    if parent_mode in MODES:
        mode = max(mode, parent_mode, key=MODES.index)
    return mode


def is_dangerous(name, arguments):
    # Unknown tools, scripts, browser actions and external MCP are reviewed.
    # Never trust model-provided descriptions or readOnlyHint annotations.
    from .lsm_tool_registry import _READ_TOOLS

    if name in _READ_TOOLS or name in {"web_search", "web_fetch", "ask_user_question", "subagent"}:
        return False
    if name == "browser_session":
        return arguments.get("action") != "list"
    if name == "session_manage":
        return arguments.get("action") not in ("start", "get", "report", "finish")
    if name == "plan_manage":
        return arguments.get("action") not in ("get", "update")
    # Only exact, argument-free read commands. Do not parse arbitrary shell
    # syntax: redirects, substitutions, env assignments, etc. require review.
    if name == "run_shell":
        return arguments.get("command") not in ("ls", "pwd")
    return True


def call_decision(mode, legacy_policy, name, arguments):
    # Preserve explicitly configured legacy deny/ask policy. The new modes
    # never expand machine grants or override an existing explicit denial.
    policy = ask_user_approval_policy(legacy_policy) if name == "ask_user_question" else legacy_policy
    legacy = approval_policy_decision(policy, name)
    if legacy and legacy["decision"] in {"deny", "ask"}:
        return legacy
    if name != "ask_user_question" and (mode == "all" or mode == "dangerous" and is_dangerous(name, arguments)):
        return {"decision": "ask"}
    return legacy
