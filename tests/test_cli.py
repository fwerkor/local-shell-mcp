import local_shell_mcp.main as cli


def test_server_options_parse_to_default_handler():
    args = cli._build_parser().parse_args(
        ["--config", "config.yaml", "--mode", "stdio", "--no-remote"]
    )

    assert args.handler is cli._run_server_from_args
    assert args.config == "config.yaml"
    assert args.mode == "stdio"
    assert args.remote is False


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
        calls.append((args.mode, args.remote))

    monkeypatch.setattr(cli, "_run_server_from_args", run_from_args)

    cli.main(["--mode", "stdio", "--remote"])

    assert calls == [("stdio", True)]
