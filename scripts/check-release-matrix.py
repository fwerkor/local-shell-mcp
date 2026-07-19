#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
RELEASE = REPO / ".github" / "workflows" / "release.yml"
EXPECTED_BINARY_ARTIFACTS = {
    "linux-x86_64",
    "linux-aarch64",
    "macos-x86_64",
    "macos-aarch64",
    "windows-x86_64",
}
EXPECTED_PYTHON_ARTIFACTS = EXPECTED_BINARY_ARTIFACTS
EXPECTED_DOCKER_PLATFORMS = {"linux/amd64", "linux/arm64"}


def matrix_values(job: dict, key: str) -> set[str]:
    rows = job.get("strategy", {}).get("matrix", {}).get("include", [])
    return {str(row[key]) for row in rows if key in row}


def step_script(job: dict, name: str) -> str:
    for step in job.get("steps", []):
        if step.get("name") == name:
            return str(step.get("run") or "")
    return ""


def main() -> int:
    workflow = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})

    python_job = jobs.get("build-python-package", {})
    python_artifacts = matrix_values(python_job, "artifact")
    missing_python = sorted(EXPECTED_PYTHON_ARTIFACTS - python_artifacts)
    extra_python = sorted(python_artifacts - EXPECTED_PYTHON_ARTIFACTS)
    if missing_python or extra_python:
        print("Release Python wheel matrix mismatch.")
        print(f"missing: {missing_python}")
        print(f"extra: {extra_python}")
        return 1

    ui_build_script = step_script(python_job, "Build OpenTUI runtime and embedded WebUI")
    if "bun run build" not in ui_build_script:
        print("Release wheels must compile the platform-native OpenTUI runtime.")
        return 1

    wheel_build_script = step_script(python_job, "Build platform wheel")
    if "python -m build --wheel" not in wheel_build_script:
        print("Release wheels must be built directly from the platform checkout.")
        return 1

    wheel_smoke_script = step_script(python_job, "Install wheel and smoke test packaged UI")
    if "standalone-ui-smoke.py" not in wheel_smoke_script:
        print("Release wheels must exercise their packaged OpenTUI runtime.")
        return 1

    binary_job = jobs.get("build-binary", {})
    binary_artifacts = matrix_values(binary_job, "artifact")
    missing_binary = sorted(EXPECTED_BINARY_ARTIFACTS - binary_artifacts)
    extra_binary = sorted(binary_artifacts - EXPECTED_BINARY_ARTIFACTS)
    if missing_binary or extra_binary:
        print("Release binary matrix mismatch.")
        print(f"missing: {missing_binary}")
        print(f"extra: {extra_binary}")
        return 1

    package_script = step_script(binary_job, "Package executable")
    if not package_script:
        print("Release binary packaging step is missing.")
        return 1
    if "matrix.tui_binary" in package_script:
        print("Release archives must not include the OpenTUI sidecar executable.")
        return 1

    smoke_script = step_script(binary_job, "Smoke test embedded OpenTUI runtime")
    if "standalone-ui-smoke.py" not in smoke_script:
        print("Release binaries must exercise the embedded OpenTUI runtime before packaging.")
        return 1

    docker_job = jobs.get("publish-docker-platform", {})
    docker_platforms = matrix_values(docker_job, "platform")
    missing_docker = sorted(EXPECTED_DOCKER_PLATFORMS - docker_platforms)
    extra_docker = sorted(docker_platforms - EXPECTED_DOCKER_PLATFORMS)
    if missing_docker or extra_docker:
        print("Release Docker matrix mismatch.")
        print(f"missing: {missing_docker}")
        print(f"extra: {extra_docker}")
        return 1

    print(
        "Release build matrices, platform wheels, and single-executable packaging checks passed for all expected platforms."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
