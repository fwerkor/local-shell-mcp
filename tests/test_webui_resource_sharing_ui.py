"""The single-user controller does not expose legacy resource-sharing ACLs."""
from pathlib import Path


def test_resource_editors_do_not_mount_legacy_sharing():
    components = Path(__file__).resolve().parents[1] / "ui/workspace/client/src/components"
    for directory in ("SidePanel/Agents", "SidePanel/MCPBuilder", "Skills", "Prompts"):
        for path in (components / directory).rglob("*.tsx"):
            source = path.read_text(encoding="utf-8")
            for legacy_component in ("GenericGrantAccessDialog", "ShareSkill", "SharePrompt"):
                assert legacy_component not in source, (path, legacy_component)
