from pathlib import Path
from runpy import run_path

import pytest

pinned_action = run_path(str(Path(__file__).resolve().parents[1] / "scripts/check-release-matrix.py"))[
    "pinned_action"
]
BUILD_SHA = "3bdaa03e1ba6bf59a65f84a751d943d549a54e79"


@pytest.mark.parametrize(
    ("ref", "valid"),
    [
        (f"snapcore/action-build@{BUILD_SHA}", True),
        ("snapcore/action-build@v1", False),
        (f"snapcore/action-build@{BUILD_SHA[:-1]}", False),
        (f"snapcore/action-build@{BUILD_SHA}a", False),
        (f"other/action-build@{BUILD_SHA}", False),
        (f"snapcore/action-publish@{BUILD_SHA}", False),
    ],
)
def test_snap_build_action_requires_pinned_sha(ref: str, valid: bool) -> None:
    assert pinned_action({"uses": ref}, "snapcore/action-build") is valid
