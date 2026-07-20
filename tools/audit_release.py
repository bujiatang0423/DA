"""Fail release checks when DA's runtime surface loses its local safety boundary."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re


_RUNTIME_ROOTS = (
    Path("backend/app"),
    Path("web/src"),
    Path("strategies"),
    Path("contracts"),
    Path("scripts"),
    Path("pyproject.toml"),
)
_FORBIDDEN_REFERENCES = (
    "/Users/bujiatang/workspace/LA",
    "../LA/",
    "PYTHONPATH",
)
_CONTROLLED_LOGGING_MODULE = Path("backend/app/infrastructure/logging.py")
_ALLOWED_PRINT_MODULES = (Path("backend/app/features/legacy_import/cli.py"),)


def audit_repository(root: Path) -> list[str]:
    """Return stable release blockers without echoing file contents or secret values."""
    findings: list[str] = []
    for path in _runtime_files(root):
        relative = path.relative_to(root)
        display_path = relative.as_posix()
        if path.is_symlink():
            findings.append(f"symlink:{display_path}")
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for forbidden in _FORBIDDEN_REFERENCES:
            if forbidden in content:
                findings.append(f"forbidden-reference:{display_path}:{forbidden}")
        if _uses_uncontrolled_logging(relative, content):
            findings.append(f"uncontrolled-logging:{display_path}")
        if _uses_uncontrolled_print(relative, content):
            findings.append(f"uncontrolled-print:{display_path}")
    return findings


def _runtime_files(root: Path) -> Iterable[Path]:
    for relative in _RUNTIME_ROOTS:
        candidate = root / relative
        if candidate.is_symlink() or candidate.is_file():
            yield candidate
        elif candidate.is_dir():
            yield from sorted(
                path for path in candidate.rglob("*") if path.is_file() or path.is_symlink()
            )


def _uses_uncontrolled_logging(relative: Path, content: str) -> bool:
    if relative == _CONTROLLED_LOGGING_MODULE:
        return False
    return "import logging" in content or "from logging " in content


def _uses_uncontrolled_print(relative: Path, content: str) -> bool:
    if relative in _ALLOWED_PRINT_MODULES:
        return False
    return re.search(r"(?<![A-Za-z0-9_])print\(", content) is not None


def main() -> None:
    findings = audit_repository(Path("."))
    if findings:
        raise SystemExit("\n".join(findings))


if __name__ == "__main__":
    main()
