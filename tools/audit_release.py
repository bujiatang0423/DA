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
    entries = [
        (key.value, value)
        for key, value in zip(event_dicts[0].keys, event_dicts[0].values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and value is not None
    ]
    return (
        len(entries) == len(_REQUEST_EVENT_FIELDS)
        and {key for key, _ in entries} == _REQUEST_EVENT_FIELDS
        and all(_is_approved_event_value(key, value) for key, value in entries)
    )


def _is_approved_event_value(key: str, value: ast.expr) -> bool:
    if key == "timestamp":
        return _is_utc_timestamp(value)
    if key == "level":
        return _constant_string(value) == "INFO"
    if key == "request_id":
        return _name_is(value, "request_id")
    if key == "method":
        return _name_is(value, "method")
    if key == "path_template":
        return _name_is(value, "path_template")
    if key == "status_code":
        return _name_is(value, "status_code")
    if key == "run_id":
        return _is_safe_request_run_id(value)
    return key == "event_code" and _name_is(value, "_REQUEST_EVENT_CODE")


def _is_utc_timestamp(value: ast.expr) -> bool:
    if not isinstance(value, ast.Call) or value.args or value.keywords:
        return False
    if not isinstance(value.func, ast.Attribute) or value.func.attr != "isoformat":
        return False
    now = value.func.value
    return (
        isinstance(now, ast.Call)
        and isinstance(now.func, ast.Attribute)
        and _name_is(now.func.value, "datetime")
        and now.func.attr == "now"
        and len(now.args) == 1
        and _name_is(now.args[0], "UTC")
        and not now.keywords
    )


def _is_safe_request_run_id(value: ast.expr) -> bool:
    if not isinstance(value, ast.Call) or not _name_is(value.func, "safe_run_id"):
        return False
    return len(value.args) == 1 and _name_is(value.args[0], "run_id") and not value.keywords


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
    entries = [
        (key.value, value)
        for key, value in zip(dumped.args[0].keys, dumped.args[0].values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and value is not None
    ]
    return (
        len(entries) == 4
        and {key for key, _ in entries}
        == {"batch_id", "effective_at", "manifest_sha256", "idempotent"}
        and all(_is_approved_legacy_import_value(key, value) for key, value in entries)
        and len(dumped.keywords) == 1
        and dumped.keywords[0].arg == "ensure_ascii"
        and isinstance(dumped.keywords[0].value, ast.Constant)
        and dumped.keywords[0].value.value is False
    )


def _is_approved_legacy_import_value(key: str, value: ast.expr) -> bool:
    if key == "effective_at":
        return _is_batch_effective_at(value)
    return _attribute_is(value, "batch", key)


def _is_batch_effective_at(value: ast.expr) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and _attribute_is(value.func.value, "batch", "effective_at")
        and value.func.attr == "isoformat"
        and not value.args
        and not value.keywords
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
        _constant_string(node.args[0]) == "artifact hash verification failed"
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
