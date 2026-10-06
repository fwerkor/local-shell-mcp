import hashlib
import os
import subprocess
import sys
from pathlib import Path

HOST_ONLY_SETTINGS = {"LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN"}


def test_compose_forwards_every_example_service_setting() -> None:
    example_lines = Path('.env.example').read_text(encoding='utf-8').splitlines()
    example_settings = {
        line.split('=', 1)[0]
        for line in example_lines
        if line.startswith('LOCAL_SHELL_MCP_') and '=' in line
    }
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')

    missing = sorted(
        name
        for name in example_settings - HOST_ONLY_SETTINGS
        if f'${{{name}' not in compose
    )
    assert missing == []
    assert "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN:" not in compose
    assert "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256:" in compose
    assert (
        '127.0.0.1:${LOCAL_SHELL_MCP_PORT:-8765}:${LOCAL_SHELL_MCP_PORT:-8765}'
        in compose
    )
    assert 'LOCAL_SHELL_MCP_PORT: "${LOCAL_SHELL_MCP_PORT:-8765}"' in compose
    assert "LOCAL_SHELL_MCP_PORT=8765" in Path('.env.example').read_text(encoding='utf-8')


def test_compose_cli_credential_rotation_rewrites_existing_assignments(tmp_path) -> None:
    env_path = tmp_path / '.env'
    env_path.write_text(
        'KEEP=value\n'
        'LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=old-token\n'
        'LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=old-verifier\n',
        encoding='utf-8',
    )
    if os.name != 'nt':
        env_path.chmod(0o644)
    script = Path(__file__).parents[1] / 'scripts' / 'init_compose_env.py'
    initial_inode = env_path.stat().st_ino
    if os.name != 'nt':
        assert env_path.stat().st_mode & 0o777 == 0o644

    subprocess.run([sys.executable, str(script), str(env_path)], check=True, capture_output=True)
    first_inode = env_path.stat().st_ino
    assert first_inode != initial_inode
    first = dict(
        line.split('=', 1)
        for line in env_path.read_text(encoding='utf-8').splitlines()
        if '=' in line
    )
    first_token = first['LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN']
    first_verifier = first['LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256']
    assert first_verifier == hashlib.sha256(first_token.encode()).hexdigest()

    subprocess.run([sys.executable, str(script), str(env_path)], check=True, capture_output=True)
    second_inode = env_path.stat().st_ino
    assert second_inode != first_inode
    lines = env_path.read_text(encoding='utf-8').splitlines()
    second = dict(line.split('=', 1) for line in lines if '=' in line)
    second_token = second['LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN']
    second_verifier = second['LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256']

    assert second_verifier == hashlib.sha256(second_token.encode()).hexdigest()
    assert lines.count(f'LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN={second_token}') == 1
    assert lines.count(f'LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256={second_verifier}') == 1
    assert not any(first_token in line or first_verifier in line for line in lines)
    assert 'KEEP=value' in lines
    if os.name != 'nt':
        assert env_path.stat().st_mode & 0o777 == 0o600
