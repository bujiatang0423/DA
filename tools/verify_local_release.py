"""Run the local release safety checks twice to prove repeatability."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_PYTEST_TARGETS = (
    "backend/tests/system/test_release_audit.py",
    "backend/tests/test_independent_paths.py",
)


def _run(command: tuple[str, ...]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def _run_once() -> None:
    _run((sys.executable, "-m", "pytest", *_PYTEST_TARGETS, "-q"))
    _run((sys.executable, "-m", "tools.audit_release"))
    _run((sys.executable, "-m", "tools.export_openapi"))
    _run(("git", "diff", "--exit-code", "--", "contracts/openapi.json"))


def main() -> None:
    for _ in range(2):
        _run_once()


if __name__ == "__main__":
    main()
