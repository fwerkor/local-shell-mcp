from pathlib import Path


def test_compose_forwards_every_example_service_setting() -> None:
    example_lines = Path('.env.example').read_text(encoding='utf-8').splitlines()
    example_settings = {
        line.split('=', 1)[0]
        for line in example_lines
        if line.startswith('LOCAL_SHELL_MCP_') and '=' in line
    }
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')

    missing = sorted(name for name in example_settings if f'${{{name}' not in compose)
    assert missing == []
