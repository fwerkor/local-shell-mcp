"""LibreChat 0.8.8 Agent Artifacts prompt selection.

The templates and shadcn component records are snapshots of the pinned upstream
sources. The controller reads data from its installed Python package, never
executes Node or downloads templates during generation.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def _source() -> dict:
    return json.loads(
        files("local_shell_mcp.webui")
        .joinpath("artifact_prompt_snapshot.json")
        .read_text(encoding="utf-8")
    )


def _dedent(value: str) -> str:
    """Match the pinned JS dedent template tag on already-interpolated text."""
    lines = value.split("\n")
    indents = [len(match.group(1)) for line in lines if (match := re.match(r"^(\s+)\S+", line))]
    if indents:
        indent = min(indents)
        value = "\n".join(line[indent:] if line[:1] in {" ", "\t"} else line for line in lines)
    return value.strip().replace(r"\n", "\n")


def _shadcn_prompt(*, xml: bool) -> str:
    """generateShadcnPrompt exact nested dedent interpolation from pinned generate.ts."""
    blocks: list[str] = []
    for item in _source()["components"]:
        if xml:
            block = f"""
            <component>
              <name>{item["name"]}</name>
              <import-instructions>{item["import"]}</import-instructions>
              <usage-instructions>{item["usage"]}</usage-instructions>
            </component>
          """
        else:
            block = f"""
            # {item["name"]}

            ## Import Instructions
            {item["import"]}

            ## Usage Instructions
            {item["usage"]}
          """
        blocks.append(_dedent(block))
    joined = "\n\n".join(blocks)
    return _dedent(f"""
    ## Additional Artifact Instructions for React Components: "application/vnd.react"
    
    There are some prestyled components (primitives) available for use. Please use your best judgement to use any of these components if the app calls for one.

    Here are the components that are available, along with how to import them, and how to use them:

    {joined}
  """)


def generate_artifacts_prompt(endpoint: str, mode: str | None) -> str | None:
    """Source generateArtifactsPrompt: custom => null, others => endpoint template.

    The upstream initializer skips calling this function for an absent/empty
    Agent capability. agent_instructions preserves that separate guard.
    """
    if mode == "custom":
        return None
    anthropic = endpoint == "anthropic"
    base = _source()["prompts"]["anthropic" if anthropic else "openai"]
    if mode == "shadcnui":
        return base + _shadcn_prompt(xml=anthropic)
    return base


def artifact_mode(payload: dict, agent: dict | None) -> str | None:
    """Request ephemeral toggle overrides persisted Agent mode, including off."""
    ephemeral = payload.get("ephemeralAgent")
    if isinstance(ephemeral, dict) and isinstance(ephemeral.get("artifacts"), str):
        return ephemeral["artifacts"]
    mode = (agent or {}).get("artifacts")
    return mode if isinstance(mode, str) else None


def agent_instructions(agent: dict | None, endpoint: str, mode: str | None = None) -> str:
    """Replicate initializeAgent appendAdditionalInstructions without editing Agent config."""
    agent = agent or {}
    selected = mode if mode is not None else agent.get("artifacts")
    result = (
        generate_artifacts_prompt(endpoint, selected)
        if isinstance(selected, str) and selected
        else None
    )
    return "\n\n".join(
        value
        for value in (
            agent.get("instructions"),
            agent.get("additional_instructions"),
            result,
        )
        if isinstance(value, str) and value
    )
