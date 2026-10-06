#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
RELEASE = REPO / ".github" / "workflows" / "release.yml"
DOCKERFILE = REPO / "Dockerfile"
SNAPCRAFT = REPO / "snap" / "snapcraft.yaml"
VSCODE_PACKAGE_SCRIPT = REPO / "vscode-extension" / "scripts" / "package-vsix.cjs"
EXPECTED_BINARY_ARTIFACTS = {
    "linux-x86_64",
    "linux-aarch64",
    "macos-x86_64",
    "macos-aarch64",
    "windows-x86_64",
}
EXPECTED_PYTHON_ARTIFACTS = EXPECTED_BINARY_ARTIFACTS
EXPECTED_SNAP_ARTIFACTS = {"linux-x86_64", "linux-aarch64"}
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
    release_text = RELEASE.read_text(encoding="utf-8")
    workflow = yaml.safe_load(release_text)
    jobs = workflow.get("jobs", {})

    if "push_latest:" in release_text or "inputs.push_latest" in release_text:
        print("Release workflow must derive stable latest tags from the prerelease flag, not a separate push_latest input.")
        return 1

    validate_job = jobs.get("validate-release", {})
    release_source_script = step_script(validate_job, "Validate release source")
    if "refs/heads/${DEFAULT_BRANCH}" not in release_source_script:
        print("Release workflow must reject dispatches outside the default branch.")
        return 1
    if "git ls-remote --exit-code origin" not in release_source_script or "GITHUB_SHA" not in release_source_script:
        print("Release workflow must verify the dispatched SHA is the current default-branch commit.")
        return 1

    docker_tag_script = step_script(validate_job, "Prepare Docker release tags")
    if 'PRERELEASE' not in docker_tag_script or "if not prerelease:" not in docker_tag_script:
        print("Docker latest tags must be emitted only for stable releases.")
        return 1

    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    if "COPY requirements-agent.txt pyproject.toml hatch_build.py README.md LICENSE /app/" not in dockerfile:
        print("Docker builds must copy hatch_build.py before installing the project.")
        return 1

    if 'python -c "import zstandard"' not in dockerfile:
        print("Docker builds must verify the zstandard audit-archive runtime dependency.")
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

    binary_build_script = step_script(binary_job, "Build self-contained executable")
    if "--collect-all zstandard" not in binary_build_script:
        print("Release standalone binaries must bundle the zstandard native extension.")
        return 1

    package_script = step_script(binary_job, "Package executable")
    if not package_script:
        print("Release binary packaging step is missing.")
        return 1
    if "matrix.tui_binary" in package_script:
        print("Release archives must not include the OpenTUI sidecar executable.")
        return 1
    if 'package_name="local-shell-mcp-${{ matrix.artifact }}"' not in package_script:
        print("Release binaries must use stable platform-specific package names.")
        return 1
    if 'package_dir="package/${package_name}"' not in package_script:
        print("Release archive staging must stay outside the published release directory.")
        return 1
    if 'raw_name="${package_name}"' not in package_script:
        print("Release binaries must publish raw platform executables for the npm launcher.")
        return 1

    upload_steps = binary_job.get("steps", [])
    binary_upload = next((step for step in upload_steps if step.get("uses", "").startswith("actions/upload-artifact@")), None)
    upload_path = str((binary_upload or {}).get("with", {}).get("path", ""))
    if "release/local-shell-mcp-${{ matrix.artifact }}*" not in upload_path:
        print("Release binary artifact upload must include extensionless raw executables.")
        return 1

    snapcraft = yaml.safe_load(SNAPCRAFT.read_text(encoding="utf-8"))
    if snapcraft.get("name") != "local-shell-mcp" or snapcraft.get("confinement") != "classic":
        print("Snapcraft package must publish local-shell-mcp with classic confinement.")
        return 1
    snap_apps = snapcraft.get("apps", {})
    if snap_apps.get("local-shell-mcp", {}).get("command") != "bin/local-shell-mcp":
        print("Snapcraft package must expose the local-shell-mcp command.")
        return 1
    snap_part = snapcraft.get("parts", {}).get("local-shell-mcp", {})
    if snap_part.get("organize", {}).get("local-shell-mcp") != "bin/local-shell-mcp":
        print("Snapcraft package must stage the release binary at bin/local-shell-mcp.")
        return 1
    snap_job = jobs.get("build-snap", {})
    snap_artifacts = matrix_values(snap_job, "artifact")
    missing_snap = sorted(EXPECTED_SNAP_ARTIFACTS - snap_artifacts)
    extra_snap = sorted(snap_artifacts - EXPECTED_SNAP_ARTIFACTS)
    if missing_snap or extra_snap:
        print("Release Snap matrix mismatch.")
        print(f"missing: {missing_snap}")
        print(f"extra: {extra_snap}")
        return 1
    snap_stage_script = step_script(snap_job, "Stage Snap payload")
    if "needs.validate-release.outputs.version" not in release_text or "snap/version" not in snap_stage_script:
        print("Snap builds must derive their version from validated release metadata.")
        return 1
    snap_build_step = next(
        (step for step in snap_job.get("steps", []) if step.get("name") == "Build Snap package"),
        {},
    )
    if snap_build_step.get("uses") != "snapcore/action-build@v1":
        print("Release workflow must build snaps with snapcore/action-build@v1.")
        return 1

    github_release_job = jobs.get("github-release", {})
    checksum_script = step_script(github_release_job, "Generate SHA256 checksums")
    if "find . -maxdepth 1 -type f" not in checksum_script:
        print("GitHub release checksums must only enumerate regular release files.")
        return 1
    if 'sha256sum -- "${files[@]}" > SHA256SUMS' not in checksum_script:
        print("GitHub releases must publish SHA256SUMS for npm launcher verification.")
        return 1

    npm_job = jobs.get("publish-npm", {})
    npm_publish_script = step_script(npm_job, "Publish npm launcher")
    if "npm publish" not in npm_publish_script or npm_job.get("environment") != "npm":
        print("Release workflow must publish the npm launcher from the protected npm environment.")
        return 1
    if "--tag next" not in npm_publish_script or "--tag latest" not in npm_publish_script:
        print("npm prereleases must use a non-latest dist-tag while stable releases update latest.")
        return 1

    dsh_npm_job = jobs.get("publish-dsh-npm", {})
    dsh_npm_publish_script = step_script(dsh_npm_job, "Publish DSH npm plugin")
    dsh_npm_prepare_script = step_script(dsh_npm_job, "Prepare DSH npm plugin version")
    if "npm publish" not in dsh_npm_publish_script or dsh_npm_job.get("environment") != "npm":
        print("Release workflow must publish the DSH npm plugin from the protected npm environment.")
        return 1
    if "npm version" not in dsh_npm_prepare_script or "RELEASE_VERSION" not in dsh_npm_prepare_script:
        print("DSH npm publication must derive its version from validated release metadata.")
        return 1
    if "--tag next" not in dsh_npm_publish_script or "--tag latest" not in dsh_npm_publish_script:
        print("DSH npm prereleases must use a non-latest dist-tag while stable releases update latest.")
        return 1

    snap_publish_job = jobs.get("publish-snap", {})
    if snap_publish_job.get("environment") != "snapcraft":
        print("Snap Store publication must run from the protected snapcraft environment.")
        return 1
    if "SNAP_PUBLISH_ENABLED" not in str(snap_publish_job.get("if") or ""):
        print("Snap Store publication must be controlled by SNAP_PUBLISH_ENABLED.")
        return 1
    snap_publish_step = next(
        (step for step in snap_publish_job.get("steps", []) if step.get("name") == "Publish Snap package"),
        {},
    )
    if snap_publish_step.get("uses") != "snapcore/action-publish@v1":
        print("Release workflow must publish snaps with snapcore/action-publish@v1.")
        return 1
    snap_release = str(snap_publish_step.get("with", {}).get("release", ""))
    if "edge" not in snap_release or "stable" not in snap_release or "prerelease" not in snap_release:
        print("Snap prereleases must publish to edge while stable releases publish to stable.")
        return 1

    pypi_job = jobs.get("publish-pypi", {})
    if pypi_job.get("environment") != "pypi":
        print("Release workflow must publish Python artifacts from the protected pypi environment.")
        return 1
    if "!inputs.prerelease" not in str(pypi_job.get("if") or ""):
        print("PyPI publication must be limited to stable releases so prereleases cannot replace the default install.")
        return 1
    if step_script(pypi_job, "Exclude raw Linux wheels unsupported by PyPI"):
        print("PyPI publishing must not discard validated manylinux wheels.")
        return 1

    vscode_job = jobs.get("build-vscode-extension", {})
    vscode_package_script = step_script(vscode_job, "Package VSIX")
    package_script_text = VSCODE_PACKAGE_SCRIPT.read_text(encoding="utf-8")
    if "--pre-release" not in vscode_package_script or 'args.push("--pre-release")' not in package_script_text:
        print("VSIX prereleases must be packaged with the Marketplace/Open VSX prerelease marker.")
        return 1

    vscode_publish_job = jobs.get("publish-vscode-marketplace", {})
    if "--pre-release" not in step_script(vscode_publish_job, "Publish extension"):
        print("VS Code Marketplace prereleases must publish through the prerelease channel.")
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
