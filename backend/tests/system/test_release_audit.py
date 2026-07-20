from __future__ import annotations

from pathlib import Path

from tools.audit_release import audit_repository


def test_release_audit_accepts_the_repository_runtime_surface() -> None:
    findings = audit_repository(Path("."))

    assert findings == []
    openapi = Path("contracts/openapi.json").read_text(encoding="utf-8")
    assert "research" in openapi
    assert "pit_verified" in openapi


def test_release_audit_rejects_a_runtime_reference_to_la(tmp_path: Path) -> None:
    runtime_file = tmp_path / "backend" / "app" / "provider.py"
    runtime_file.parent.mkdir(parents=True)
    forbidden = "/Users/bujiatang/workspace/" + "LA"
    runtime_file.write_text(f'SOURCE = "{forbidden}/data"\n', encoding="utf-8")

    assert audit_repository(tmp_path) == [
        f"forbidden-reference:backend/app/provider.py:{forbidden}"
    ]


def test_release_audit_rejects_symlinks_and_uncontrolled_runtime_logging(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("pass\n", encoding="utf-8")
    linked = tmp_path / "backend" / "app" / "linked.py"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(target)
    logging_source = tmp_path / "backend" / "app" / "feature.py"
    logging_source.write_text("import logging\nlogging.info(request_body)\n", encoding="utf-8")

    assert audit_repository(tmp_path) == [
        "uncontrolled-logging:backend/app/feature.py",
        "symlink:backend/app/linked.py",
    ]


def test_release_audit_rejects_unsafe_sinks_inside_previously_allowed_modules(
    tmp_path: Path,
) -> None:
    logging_source = tmp_path / "backend" / "app" / "infrastructure" / "logging.py"
    logging_source.parent.mkdir(parents=True)
    logging_source.write_text("import logging\nlogging.warning(secret)\n", encoding="utf-8")
    legacy_cli = tmp_path / "backend" / "app" / "features" / "legacy_import" / "cli.py"
    legacy_cli.parent.mkdir(parents=True)
    legacy_cli.write_text("print(secret)\n", encoding="utf-8")
    artifact_tool = tmp_path / "tools" / "verify_artifact_hashes.py"
    artifact_tool.parent.mkdir(parents=True)
    artifact_tool.write_text("print(secret)\n", encoding="utf-8")

    assert audit_repository(tmp_path) == [
        "uncontrolled-print:backend/app/features/legacy_import/cli.py",
        "uncontrolled-logging:backend/app/infrastructure/logging.py",
        "uncontrolled-print:tools/verify_artifact_hashes.py",
    ]
