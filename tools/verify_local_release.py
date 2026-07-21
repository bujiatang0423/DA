"""Run the local release safety checks twice to prove repeatability."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_PYTEST_TARGETS = (
    "backend/tests/system/test_release_audit.py",
    "backend/tests/test_independent_paths.py",
    "backend/tests/features/backtests/test_engine.py",
    "backend/tests/features/backtests/test_pit_audit.py",
    "backend/tests/infrastructure/market/test_strict_bundle.py",
)
_POSTGRES_URL = "postgresql+psycopg://da:da@127.0.0.1:5432/da_test"


def _run(
    command: tuple[str, ...], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> None:
    subprocess.run(command, cwd=cwd, check=True, env=env)


def _postgres_command() -> tuple[str, ...]:
    return ("-m", "pytest", "-m", "postgres", "-q")


def _postgres_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["TEST_DATABASE_URL"] = _POSTGRES_URL
    return environment


def _run_once(*, include_postgres: bool, include_e2e: bool) -> None:
    _run((sys.executable, "-m", "pytest", *_PYTEST_TARGETS, "-q"))
    if include_postgres:
        _run((sys.executable, *_postgres_command()), env=_postgres_environment())
    if include_e2e:
        _run(("npm", "run", "e2e"), cwd=ROOT / "web")
    _run((sys.executable, "-m", "tools.audit_release"))
    _run((sys.executable, "-m", "tools.export_openapi"))
    _run(("git", "diff", "--exit-code", "--", "contracts/openapi.json"))


def main() -> None:
    include_postgres = "--postgres" in sys.argv[1:]
    include_e2e = "--e2e" in sys.argv[1:]
    passes = 2
    for argument in sys.argv[1:]:
        if argument.startswith("--passes="):
            passes = int(argument.removeprefix("--passes="))
    if passes < 1:
        raise SystemExit("--passes must be positive")
    for _ in range(passes):
        _run_once(include_postgres=include_postgres, include_e2e=include_e2e)


if __name__ == "__main__":
    main()
