from pathlib import Path
from runpy import run_path

import pytest

pinned_action = run_path(str(Path(__file__).resolve().parents[1] / "scripts/check-release-matrix.py"))[
    "pinned_action"
]
BUILD_SHA = "3bdaa03e1ba6bf59a65f84a751d943d549a54e79"
PUBLISH_SHA = "214b86e5ca036ead1668c79afb81e550e6c54d40"


@pytest.mark.parametrize(
    ("ref", "valid"),
    [
        (f"snapcore/action-build@{BUILD_SHA}", True),
        (f"snapcore/action-build@{'a' * 40}", False),
        ("snapcore/action-build@v1", False),
        (f"snapcore/action-build@{BUILD_SHA[:-1]}", False),
        (f"snapcore/action-build@{BUILD_SHA}a", False),
        (f"other/action-build@{BUILD_SHA}", False),
        (f"snapcore/action-publish@{BUILD_SHA}", False),
    ],
)
def test_snap_build_action_requires_pinned_sha(ref: str, valid: bool) -> None:
    assert pinned_action({"uses": ref}, "snapcore/action-build") is valid


def test_snap_publish_action_requires_approved_commit() -> None:
    assert pinned_action({"uses": f"snapcore/action-publish@{PUBLISH_SHA}"}, "snapcore/action-publish")
    assert not pinned_action({"uses": f"snapcore/action-publish@{BUILD_SHA}"}, "snapcore/action-publish")
    assert not pinned_action({"uses": f"snapcore/action-publish@{PUBLISH_SHA}"}, "unknown/action")
