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
EXPECTED_DOCKER_PLATFORMS = {"linux/amd64", "linux/arm64"}


def matrix_values(job: dict, key: str) -> set[str]:
    rows = job.get("strategy", {}).get("matrix", {}).get("include", [])
    return {str(row[key]) for row in rows if key in row}


def main() -> int:
    workflow = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})

    binary_job = jobs.get("build-binary", {})
    binary_artifacts = matrix_values(binary_job, "artifact")
    missing_binary = sorted(EXPECTED_BINARY_ARTIFACTS - binary_artifacts)
    extra_binary = sorted(binary_artifacts - EXPECTED_BINARY_ARTIFACTS)
    if missing_binary or extra_binary:
        print("Release binary matrix mismatch.")
        print(f"missing: {missing_binary}")
        print(f"extra: {extra_binary}")
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

    print("Release build matrices cover all expected binary artifacts and Docker platforms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
