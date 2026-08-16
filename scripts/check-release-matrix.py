#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
RELEASE = REPO / ".github" / "workflows" / "release.yml"
DOCKERFILE = REPO / "Dockerfile"
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

    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    if "COPY requirements-agent.txt pyproject.toml hatch_build.py README.md LICENSE /app/" not in dockerfile:
        print("Docker builds must copy hatch_build.py before installing the project.")
        return 1

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

    wheel_validation_script = step_script(python_job, "Validate wheel platform compatibility")
    if "check-wheel-compatibility.py" not in wheel_validation_script:
        print("Release wheels must validate their platform tags and native runtime compatibility.")
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
    if 'raw_name="local-shell-mcp-${{ matrix.artifact }}"' not in package_script:
        print("Release binaries must publish raw platform executables for the npm launcher.")
        return 1

    upload_steps = binary_job.get("steps", [])
    binary_upload = next((step for step in upload_steps if step.get("uses", "").startswith("actions/upload-artifact@")), None)
    upload_path = str((binary_upload or {}).get("with", {}).get("path", ""))
    if "release/local-shell-mcp-${{ matrix.artifact }}*" not in upload_path:
        print("Release binary artifact upload must include extensionless raw executables.")
        return 1

    github_release_job = jobs.get("github-release", {})
    checksum_script = step_script(github_release_job, "Generate SHA256 checksums")
    if "sha256sum * > SHA256SUMS" not in checksum_script:
        print("GitHub releases must publish SHA256SUMS for npm launcher verification.")
        return 1

    npm_job = jobs.get("publish-npm", {})
    npm_publish_script = step_script(npm_job, "Publish npm launcher")
    if "npm publish" not in npm_publish_script or npm_job.get("environment") != "npm":
        print("Release workflow must publish the npm launcher from the protected npm environment.")
        return 1

    pypi_job = jobs.get("publish-pypi", {})
    if pypi_job.get("environment") != "pypi":
        print("Release workflow must publish Python artifacts from the protected pypi environment.")
        return 1
    if step_script(pypi_job, "Exclude raw Linux wheels unsupported by PyPI"):
        print("PyPI publishing must not discard validated manylinux wheels.")
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
