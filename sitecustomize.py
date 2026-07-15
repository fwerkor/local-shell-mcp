"""Enable opt-in coverage collection in test subprocesses.

The repository root is not packaged, so production installs do not import this
module. CI smoke tests add the checkout to ``PYTHONPATH`` and set
``COVERAGE_PROCESS_START`` explicitly.
"""

from __future__ import annotations

import os

if os.getenv("COVERAGE_PROCESS_START"):
    import coverage

    coverage.process_startup()
