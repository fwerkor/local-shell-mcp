from local_shell_mcp.errors import (
    PathNotFoundError,
    process_start_not_found_error,
    workspace_path_not_found_error,
)


def test_process_start_detects_missing_cwd_without_matching_filename(tmp_path):
    missing_cwd = tmp_path / "vanished"
    exc = FileNotFoundError(2, "No such file or directory", "/bin/sh")

    result = process_start_not_found_error(
        exc,
        executable="/bin/sh",
        command="echo ok",
        cwd=missing_cwd,
    )

    assert isinstance(result, PathNotFoundError)
    assert result.path == missing_cwd


def test_workspace_path_detection_ignores_non_workspace_paths(tmp_path):
    relative = FileNotFoundError(2, "No such file or directory", "relative.txt")
    outside = FileNotFoundError(2, "No such file or directory", str(tmp_path.parent / "outside"))

    assert workspace_path_not_found_error(relative, tmp_path) is None
    assert workspace_path_not_found_error(outside, tmp_path) is None
