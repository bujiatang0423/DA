"""Fail release checks when DA's runtime surface loses its local safety boundary."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
import re


_RUNTIME_ROOTS = (
    Path("backend/app"),
    Path("web/src"),
    Path("strategies"),
    Path("contracts"),
    Path("scripts"),
    Path("tools"),
    Path("pyproject.toml"),
)
_FORBIDDEN_REFERENCES = (
    "/Users/bujiatang/workspace/" + "LA",
    "../" + "LA/",
    "PYTHON" + "PATH",
)
_CONTROLLED_LOGGING_MODULE = Path("backend/app/infrastructure/logging.py")
_LEGACY_IMPORT_CLI = Path("backend/app/features/legacy_import/cli.py")
_ARTIFACT_VERIFICATION_CLI = Path("tools/verify_artifact_hashes.py")
_REQUEST_EVENT_FIELDS = {
    "timestamp",
    "level",
    "request_id",
    "method",
    "path_template",
    "status_code",
    "run_id",
    "event_code",
}


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
            yield from sorted(path for path in candidate.rglob("*") if _is_runtime_file(path))


def _is_runtime_file(path: Path) -> bool:
    return (
        (path.is_file() or path.is_symlink())
        and path.suffix != ".pyc"
        and "__pycache__" not in path.parts
    )


def _uses_uncontrolled_logging(relative: Path, content: str) -> bool:
    direct_import = "import " + "logging"
    from_import = "from " + "logging "
    if direct_import not in content and from_import not in content:
        return False
    if relative != _CONTROLLED_LOGGING_MODULE:
        return True
    return not _is_approved_request_logger(content)


def _uses_uncontrolled_print(relative: Path, content: str) -> bool:
    if re.search(r"(?<![A-Za-z0-9_])print\(", content) is None:
        return False
    if relative == _LEGACY_IMPORT_CLI:
        return not _is_approved_legacy_import_output(content)
    if relative == _ARTIFACT_VERIFICATION_CLI:
        return not _is_approved_artifact_verification_output(content)
    return True


def _is_approved_request_logger(content: str) -> bool:
    try:
        module = ast.parse(content)
    except SyntaxError:
        return False
    imports = [node for node in module.body if isinstance(node, ast.Import)]
    if not any(
        any(alias.name == "logging" and alias.asname is None for alias in node.names)
        for node in imports
    ):
        return False
    if not _event_has_only_allowlisted_fields(module):
        return False
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and _call_uses_name(node, "logging"):
            if not _is_approved_logging_call(node):
                return False
        if isinstance(node, ast.Call) and _call_uses_name(node, "_REQUEST_LOGGER"):
            if not _is_approved_request_logger_call(node):
                return False
        if isinstance(node, ast.Attribute) and _attribute_root_name(node) == "logging":
            if node.attr not in {"getLogger", "StreamHandler", "Formatter", "INFO"}:
                return False
    return True


def _event_has_only_allowlisted_fields(module: ast.Module) -> bool:
    event_dicts = [
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "event" for target in node.targets)
        and isinstance(node.value, ast.Dict)
    ]
    if len(event_dicts) != 1:
        return False
    keys = {
        key.value
        for key in event_dicts[0].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    return keys == _REQUEST_EVENT_FIELDS


def _is_approved_logging_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
        return False
    if node.func.attr == "getLogger":
        return len(node.args) == 1 and _constant_string(node.args[0]) in {
            "da.request",
            "uvicorn.access",
        }
    if node.func.attr == "StreamHandler":
        return not node.args and not node.keywords
    return (
        node.func.attr == "Formatter"
        and len(node.args) == 1
        and _constant_string(node.args[0]) == "%(message)s"
        and not node.keywords
    )


def _is_approved_request_logger_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr == "setLevel":
        return len(node.args) == 1 and _is_logging_info(node.args[0]) and not node.keywords
    if node.func.attr == "addHandler":
        return len(node.args) == 1 and _name_is(node.args[0], "handler") and not node.keywords
    if node.func.attr != "info" or len(node.args) != 1 or node.keywords:
        return False
    return _is_approved_event_json(node.args[0])


def _is_approved_event_json(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if not _name_is(node.func.value, "json") or node.func.attr != "dumps" or len(node.args) != 1:
        return False
    if not _name_is(node.args[0], "event"):
        return False
    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
    return (
        set(keywords) == {"separators", "sort_keys"}
        and isinstance(keywords["separators"], ast.Tuple)
        and [_constant_string(item) for item in keywords["separators"].elts] == [",", ":"]
        and isinstance(keywords["sort_keys"], ast.Constant)
        and keywords["sort_keys"].value is True
    )


def _is_approved_legacy_import_output(content: str) -> bool:
    module = _parse_module(content)
    if module is None:
        return False
    calls = _print_calls(module)
    return len(calls) == 1 and _is_legacy_import_summary(calls[0])


def _is_legacy_import_summary(node: ast.Call) -> bool:
    if len(node.args) != 1 or node.keywords or not isinstance(node.args[0], ast.Call):
        return False
    dumped = node.args[0]
    if not isinstance(dumped.func, ast.Attribute) or not _name_is(dumped.func.value, "json"):
        return False
    if (
        dumped.func.attr != "dumps"
        or len(dumped.args) != 1
        or not isinstance(dumped.args[0], ast.Dict)
    ):
        return False
    keys = {
        key.value
        for key in dumped.args[0].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    return keys == {"batch_id", "effective_at", "manifest_sha256", "idempotent"} and any(
        keyword.arg == "ensure_ascii"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in dumped.keywords
    )


def _is_approved_artifact_verification_output(content: str) -> bool:
    module = _parse_module(content)
    if module is None:
        return False
    calls = _print_calls(module)
    return len(calls) == 2 and all(_is_artifact_verification_output(call) for call in calls)


def _is_artifact_verification_output(node: ast.Call) -> bool:
    if len(node.args) != 1:
        return False
    if _is_generic_error_output(node):
        return True
    return _is_count_summary_output(node)


def _is_generic_error_output(node: ast.Call) -> bool:
    return (
        isinstance(node.args[0], ast.Call)
        and _name_is(node.args[0].func, "str")
        and len(node.args[0].args) == 1
        and _name_is(node.args[0].args[0], "exc")
        and len(node.keywords) == 1
        and node.keywords[0].arg == "file"
        and _attribute_is(node.keywords[0].value, "sys", "stderr")
    )


def _is_count_summary_output(node: ast.Call) -> bool:
    if node.keywords or not isinstance(node.args[0], ast.JoinedStr):
        return False
    values = node.args[0].values
    return (
        len(values) == 4
        and _constant_string(values[0]) == "verified artifact hashes: "
        and isinstance(values[1], ast.FormattedValue)
        and _attribute_is(values[1].value, "result", "verified_count")
        and _constant_string(values[2]) == "/"
        and isinstance(values[3], ast.FormattedValue)
        and _attribute_is(values[3].value, "result", "expected_count")
    )


def _parse_module(content: str) -> ast.Module | None:
    try:
        return ast.parse(content)
    except SyntaxError:
        return None


def _print_calls(module: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and _name_is(node.func, "print")
    ]


def _call_uses_name(node: ast.Call, name: str) -> bool:
    return isinstance(node.func, ast.Attribute) and _attribute_root_name(node.func) == name


def _attribute_root_name(node: ast.Attribute) -> str | None:
    value: ast.expr = node
    while isinstance(value, ast.Attribute):
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def _constant_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_logging_info(node: ast.AST) -> bool:
    return _attribute_is(node, "logging", "INFO")


def _name_is(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _attribute_is(node: ast.AST, root: str, attribute: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == root
        and node.attr == attribute
    )


def main() -> None:
    findings = audit_repository(Path("."))
    if findings:
        raise SystemExit("\n".join(findings))


if __name__ == "__main__":
    main()
