import local_shell_mcp.main as cli
from local_shell_mcp.config_registry import SETTING_SPECS, cli_overrides_from_args


def test_server_options_parse_to_default_handler():
    args = cli._build_parser().parse_args(
        [
            "--config",
            "config.yaml",
            "--mode",
            "stdio",
            "--host",
            "127.0.0.1",
            "--port",
            "9999",
            "--workspace-root",
            "/tmp/work",
            "--auth-mode",
            "none",
            "--public-base-url",
            "https://example.com",
            "--oauth-admin-pin",
            "pin",
            "--oauth-jwt-secret",
            "secret",
            "--allow-full-container",
            "true",
            "--agent-config-dir",
            "/tmp/agent-config",
            "--remote-enabled",
            "false",
        ]
    )

    assert args.handler is cli._run_server_from_args
    assert args.config == "config.yaml"
    assert args.mode == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 9999
    assert args.workspace_root == "/tmp/work"
    assert args.auth_mode == "none"
    assert args.public_base_url == "https://example.com"
    assert args.oauth_admin_pin == "pin"
    assert args.oauth_jwt_secret == "secret"
    assert args.allow_full_container is True
    assert args.agent_config_dir == "/tmp/agent-config"
    assert args.remote_enabled is False


def test_every_setting_has_cli_option():
    help_text = cli._build_parser().format_help()

    for spec in SETTING_SPECS:
        assert spec.cli_flag in help_text
        assert spec.env_var in help_text


def test_bool_cli_values_parse_explicitly():
    parser = cli._build_parser()

    assert parser.parse_args(["--allow-full-container", "true"]).allow_full_container is True
    assert parser.parse_args(["--allow-full-container", "false"]).allow_full_container is False
    assert parser.parse_args(["--remote-enabled", "no"]).remote_enabled is False
    assert parser.parse_args(["--remote-enabled", "yes"]).remote_enabled is True


def test_worker_subcommand_parse_to_worker_handler():
    args = cli._build_parser().parse_args(
        [
            "worker",
            "--server",
            "https://example.com",
            "--invite",
            "lsmcp_inv_xxxxx",
            "--name",
            "npu-4card",
            "--workdir",
            "/home/user/project",
            "--persist",
        ]
    )

    assert args.handler is cli.run_worker_from_args
    assert args.server == "https://example.com"
    assert args.invite == "lsmcp_inv_xxxxx"
    assert args.name == "npu-4card"
    assert args.workdir == "/home/user/project"
    assert args.persist is True


def test_main_dispatches_to_argparse_handler(monkeypatch):
    calls = []

    def run_from_args(args):
        calls.append((args.mode, args.remote_enabled))

    monkeypatch.setattr(cli, "_run_server_from_args", run_from_args)

    cli.main(["--mode", "stdio", "--remote-enabled", "true"])

    assert calls == [("stdio", True)]


def test_server_overrides_include_only_explicit_values():
    args = cli._build_parser().parse_args(["--mode", "stdio", "--remote-enabled", "false"])

    assert cli_overrides_from_args(args) == {
        "mode": "stdio",
        "remote_enabled": False,
    }
