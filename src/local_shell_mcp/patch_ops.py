from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_BEGIN_PATCH = "*** Begin Patch"
_END_PATCH = "*** End Patch"
_ACTION_PREFIXES = {
    "*** Add File: ": "add",
    "*** Update File: ": "update",
    "*** Delete File: ": "delete",
}


@dataclass(frozen=True)
class _PatchAction:
    operation: str
    path: str
    body: tuple[str, ...]


@dataclass
class _FileState:
    path: str
    original: str | None
    current: str | None
    mode: str


def normalize_patch_text(patch: str, cwd: str = ".") -> str:
    """Convert an apply_patch envelope to a standard unified diff."""
    envelope = patch.lstrip("\ufeff\r\n")
    if not envelope.startswith(_BEGIN_PATCH):
        return patch

    root = Path(cwd).resolve()
    actions = _parse_envelope(envelope, root)
    states: dict[str, _FileState] = {}
    order: list[str] = []

    for action in actions:
        state = states.get(action.path)
        if state is None:
            target = _resolve_target(root, action.path)
            original = _read_existing_text(target)
            mode = "100755" if target.exists() and target.stat().st_mode & 0o111 else "100644"
            state = _FileState(action.path, original, original, mode)
            states[action.path] = state
            order.append(action.path)

        if action.operation == "add":
            if state.current is not None:
                raise ValueError(f"cannot add existing file: {action.path}")
            state.current = _parse_added_file(action)
        elif action.operation == "delete":
            if state.current is None:
                raise ValueError(f"cannot delete missing file: {action.path}")
            if action.body:
                raise ValueError(f"delete action must not contain patch lines: {action.path}")
            state.current = None
        else:
            if state.current is None:
                raise ValueError(f"cannot update missing file: {action.path}")
            state.current = _apply_update(action, state.current)

    rendered = "".join(_render_file_diff(states[path]) for path in order)
    if not rendered:
        raise ValueError("patch does not contain any file changes")
    return rendered


def _parse_envelope(patch: str, root: Path) -> list[_PatchAction]:
    lines = patch.splitlines()
    if not lines or lines[0] != _BEGIN_PATCH:
        raise ValueError("apply_patch envelope must begin with '*** Begin Patch'")

    actions: list[_PatchAction] = []
    index = 1
    while index < len(lines):
        line = lines[index]
        if line == _END_PATCH:
            if any(item.strip() for item in lines[index + 1 :]):
                raise ValueError("unexpected content after '*** End Patch'")
            if not actions:
                raise ValueError("patch envelope contains no file actions")
            return actions

        operation = None
        raw_path = ""
        for prefix, candidate in _ACTION_PREFIXES.items():
            if line.startswith(prefix):
                operation = candidate
                raw_path = line[len(prefix) :]
                break
        if operation is None:
            raise ValueError(f"expected file action at envelope line {index + 1}: {line!r}")

        path = _normalize_patch_path(raw_path, root)
        index += 1
        body: list[str] = []
        while (
            index < len(lines)
            and lines[index] != _END_PATCH
            and not any(lines[index].startswith(prefix) for prefix in _ACTION_PREFIXES)
        ):
            if lines[index].startswith("*** Move to: "):
                raise ValueError("'*** Move to:' is not supported; use delete and add actions")
            body.append(lines[index])
            index += 1
        actions.append(_PatchAction(operation, path, tuple(body)))

    raise ValueError("apply_patch envelope is missing '*** End Patch'")


def _normalize_patch_path(raw_path: str, root: Path) -> str:
    path = raw_path.strip()
    if not path or "\\" in path:
        raise ValueError(f"invalid patch path: {raw_path!r}")

    filesystem_path = Path(path)
    if filesystem_path.is_absolute():
        resolved = filesystem_path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"patch path must stay within cwd: {raw_path!r}")
        relative = resolved.relative_to(root)
        if not relative.parts:
            raise ValueError(f"invalid patch path: {raw_path!r}")
        return relative.as_posix()

    candidate = PurePosixPath(path)
    if ".." in candidate.parts:
        raise ValueError(f"patch path must stay within cwd: {raw_path!r}")
    if any(part in {"", "."} for part in candidate.parts):
        raise ValueError(f"invalid patch path: {raw_path!r}")
    return candidate.as_posix()


def _resolve_target(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"patch path escapes cwd: {relative_path}")
    if target.exists() and not target.is_file():
        raise ValueError(f"patch target is not a regular file: {relative_path}")
    return target


def _read_existing_text(target: Path) -> str | None:
    if not target.exists():
        return None
    try:
        return target.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"patch target is not UTF-8 text: {target}") from exc


def _parse_added_file(action: _PatchAction) -> str:
    content: list[str] = []
    for line_number, line in enumerate(action.body, start=1):
        if not line.startswith("+"):
            raise ValueError(f"add action line {line_number} for {action.path} must start with '+'")
        content.append(line[1:])
    return "\n".join(content) + ("\n" if content else "")


def _apply_update(action: _PatchAction, text: str) -> str:
    hunks: list[tuple[list[str], bool]] = []
    current: list[str] | None = None
    end_of_file = False

    for line_number, line in enumerate(action.body, start=1):
        if line.startswith("@@"):
            if current is not None:
                hunks.append((current, end_of_file))
            current = []
            end_of_file = False
            continue
        if line == "*** End of File":
            if current is None:
                raise ValueError(f"unexpected end-of-file marker in {action.path}")
            end_of_file = True
            continue
        if current is None:
            raise ValueError(
                f"update action line {line_number} for {action.path} must follow an '@@' hunk"
            )
        if not line.startswith((" ", "+", "-")):
            raise ValueError(f"invalid hunk line {line_number} for {action.path}: {line!r}")
        current.append(line)

    if current is not None:
        hunks.append((current, end_of_file))
    if not hunks:
        raise ValueError(f"update action contains no hunks: {action.path}")

    newline = "\r\n" if "\r\n" in text else "\r" if "\r" in text and "\n" not in text else "\n"
    trailing_newline = text.endswith(("\n", "\r"))
    lines = text.splitlines()
    cursor = 0

    for hunk_number, (hunk, must_end_at_eof) in enumerate(hunks, start=1):
        old_lines = [line[1:] for line in hunk if not line.startswith("+")]
        new_lines = [line[1:] for line in hunk if not line.startswith("-")]
        if old_lines == new_lines:
            raise ValueError(f"hunk {hunk_number} for {action.path} contains no changes")

        if old_lines:
            matches = [
                start
                for start in range(cursor, len(lines) - len(old_lines) + 1)
                if lines[start : start + len(old_lines)] == old_lines
            ]
            if not matches:
                raise ValueError(f"hunk {hunk_number} does not match {action.path}")
            if len(matches) > 1:
                raise ValueError(f"hunk {hunk_number} matches multiple locations in {action.path}")
            start = matches[0]
        elif must_end_at_eof:
            start = len(lines)
        else:
            raise ValueError(
                f"hunk {hunk_number} for {action.path} has no context; use '*** End of File' for append"
            )

        if must_end_at_eof and start + len(old_lines) != len(lines):
            raise ValueError(f"hunk {hunk_number} does not match the end of {action.path}")
        lines[start : start + len(old_lines)] = new_lines
        cursor = start + len(new_lines)

    return newline.join(lines) + (newline if trailing_newline and lines else "")


def _render_file_diff(state: _FileState) -> str:
    if state.original == state.current:
        return ""

    path = state.path
    old = state.original or ""
    new = state.current or ""
    from_file = "/dev/null" if state.original is None else f"a/{path}"
    to_file = "/dev/null" if state.current is None else f"b/{path}"
    output = [f"diff --git a/{path} b/{path}\n"]
    if state.original is None:
        output.append("new file mode 100644\n")
    elif state.current is None:
        output.append(f"deleted file mode {state.mode}\n")
    diff_lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=from_file,
        tofile=to_file,
        lineterm="\n",
    )
    for line in diff_lines:
        output.append(line)
        if line.startswith((" ", "+", "-")) and not line.endswith(("\n", "\r")):
            output.append("\n\\ No newline at end of file\n")
    return "".join(output)
