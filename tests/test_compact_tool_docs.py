from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REMOVED_OPERATIONAL_TOOL_NAMES = {
    "remote_run_shell_tool",
    "remote_grep_search",
    "remote_edit_file",
    "remote_apply_patch",
    "remote_git_diff_tool",
    "remote_copy_file",
    "remote_copy_dir",
}


def test_example_prompts_use_compact_tool_surface():
    text = (REPO / "examples" / "chatgpt-prompts.md").read_text(encoding="utf-8")

    for name in REMOVED_OPERATIONAL_TOOL_NAMES:
        assert name not in text


def test_remote_setup_guides_do_not_claim_dedicated_git_tools():
    for path in (
        REPO / "docs" / "index.md",
        REPO / "docs" / "index.zh.md",
        REPO / "docs" / "index.zh-Hant.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "remote Git tools" not in text
        assert "远程 Git 工具" not in text
        assert "遠程 Git 工具" not in text
