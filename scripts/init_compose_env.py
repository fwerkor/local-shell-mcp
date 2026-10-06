from __future__ import annotations

import argparse
import hashlib
import secrets
from pathlib import Path

CLI_TOKEN_KEY = "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN"
CLI_VERIFIER_KEY = "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256"


def _set_assignment(text: str, key: str, value: str) -> str:
    prefix = f"{key}="
    output: list[str] = []
    replaced = False
    for line in text.splitlines():
        if line.startswith(prefix):
            if not replaced:
                output.append(f"{prefix}{value}")
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(f"{prefix}{value}")
    return "\n".join(output) + "\n"


def rotate_cli_credentials(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    token = secrets.token_urlsafe(48)
    verifier = hashlib.sha256(token.encode("utf-8")).hexdigest()
    text = _set_assignment(text, CLI_TOKEN_KEY, token)
    text = _set_assignment(text, CLI_VERIFIER_KEY, verifier)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return token, verifier


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate or rotate the host CLI credential in a Compose .env file."
    )
    parser.add_argument("path", nargs="?", default=".env", type=Path)
    args = parser.parse_args()
    rotate_cli_credentials(args.path)
    print(f"Updated {args.path} with a new host CLI credential and SHA-256 verifier.")


if __name__ == "__main__":
    main()
