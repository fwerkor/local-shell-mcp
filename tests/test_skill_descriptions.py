from local_shell_mcp.agent_bridge.skills import _skill_description


def test_yaml_folded_description_is_parsed():
    markdown = """---
description: >
  Diagnose failing tests
  without unsafe changes.
---
# Debugging
"""

    assert _skill_description(markdown) == (
        "Diagnose failing tests without unsafe changes."
    )


def test_toml_front_matter_description_is_parsed():
    markdown = """+++
description = "Review release artifacts safely."
+++
# Release
"""

    assert _skill_description(markdown) == "Review release artifacts safely."


def test_heading_is_used_when_no_prose_exists():
    assert _skill_description("# Heading Description\n") == "Heading Description"


def test_prose_is_preferred_over_heading():
    markdown = "# Debugging\n\nReproduce the failure first. Continue later.\n"

    assert _skill_description(markdown) == "Reproduce the failure first."


def test_description_is_bounded():
    markdown = "---\ndescription: '" + ("x" * 700) + "'\n---\n"

    description = _skill_description(markdown)

    assert len(description) == 500
    assert description.endswith("…")


def test_malformed_front_matter_falls_back_to_body():
    markdown = """---
description: [unterminated
---
# Fallback

Use the body description.
"""

    assert _skill_description(markdown) == "Use the body description."
