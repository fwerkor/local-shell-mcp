from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


class _CordisLoader(yaml.SafeLoader):
    pass


def _construct_js(loader: yaml.SafeLoader, node: yaml.Node) -> str:
    return loader.construct_scalar(node)


_CordisLoader.add_constructor("tag:yaml.org,2002:js", _construct_js)


def test_dsh_package_declares_dual_face_bundle_and_matches_python_version() -> None:
    package = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert package["name"] == "local-shell-mcp-dsh"
    assert package.get("private") is not True
    assert package["publishConfig"]["access"] == "public"
    assert package["version"] == project["version"]
    assert package["type"] == "module"
    assert package["main"] == "./dsh/index.js"
    assert package["exports"]["./client"] == "./dsh/client.js"
    assert package["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert package["dsh"]["client"]["platform"] == "web"
    assert "@deepseek-ai/dsh-client-ui-conversation" in package["dsh"]["client"]["inject"]
    assert "src/local_shell_mcp/ui_static/live-workspace.html" in package["files"]
    assert "dsh-plugin" in package["keywords"]


def test_dsh_bundle_uses_lsm_aware_full_http_bridge() -> None:
    rows = yaml.load((REPO / "cordis.patch.yml").read_text(encoding="utf-8"), Loader=_CordisLoader)
    assert isinstance(rows, list) and len(rows) == 1
    entries = rows[0]["insert"]
    assert len(entries) == 1

    bridge = entries[0]
    assert bridge["name"] == "local-shell-mcp-dsh"
    config = bridge["config"]
    assert "127.0.0.1:8765/mcp" in config["url"]
    assert "DSH_LSM_BROWSER_URL" in config["browserUrl"]
    assert "DSH_LSM_AUTHORIZATION" in config["headers"]
    assert "DSH_LSM_KEEPALIVE_INTERVAL_MS" in config["keepAliveIntervalMs"]
    assert config["reconnectInitialDelayMs"] == 500
    assert config["reconnectMaxDelayMs"] == 30_000

    text = (REPO / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "@deepseek-ai/dsh-mcp-client" not in text
    assert "--no-remote" not in text
    assert "allowRawNames" not in text


def test_dsh_bridge_keys_upstream_mcp_clients_by_dsh_session() -> None:
    host = (REPO / "dsh/index.js").read_text(encoding="utf-8")
    client = (REPO / "dsh/client.js").read_text(encoding="utf-8")

    assert "exec.agent?.session?.id" in host
    assert "sessionClient(sessionId)" in host
    assert "x-local-shell-mcp-session-affinity" in host
    assert "client.ping()" in host
    assert "live_workspace_reconnect" in host
    assert "mcp__lsm__" in host
    assert "mcp:local-shell-mcp" in host
    assert "LIVE_VIEW_PATH = '/lsm/live-workspace'" in host
    assert "LIVE_CONFIG_PATH = '/lsm/live-config'" in host

    assert "id: 'lsm-live-workspace'" in client
    assert "conversation.view" in client
    assert "ctx.sessions.scope(sessionId)" in client
    assert "local-shell-mcp:dsh:prompt" in client


def test_live_workspace_has_dsh_host_adapter_without_replacing_mcp_app_host() -> None:
    source = (REPO / "ui/src/live-workspace.ts").read_text(encoding="utf-8")

    assert "__LSM_DSH_BOOTSTRAP__" in source
    assert "requestDshLiveConfig" in source
    assert "sendDshPrompt" in source
    assert "if (!isDshHost) return await app.updateModelContext(payload)" in source
    assert "if (!isDshHost) return await app.sendMessage(payload, options)" in source
    assert "!isDshHost && sessionId" in source
