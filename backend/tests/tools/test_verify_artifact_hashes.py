import hashlib
import json
from pathlib import Path
from typing import NoReturn

import pytest

from tools import verify_artifact_hashes
from tools.verify_artifact_hashes import ArtifactVerificationError, verify_manifest


def _write_manifest(root: Path, entries: list[dict[str, str]]) -> Path:
    manifest = root / "artifact-manifest.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    return manifest


def test_verify_manifest_accepts_matching_artifact_hashes(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    artifact = root / "run-1" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'{"result":"ok"}')
    manifest = _write_manifest(
        tmp_path,
        [
            {
                "relative_path": "run-1/result.json",
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
    )

    result = verify_manifest(root, manifest)

    assert result.expected_count == 1
    assert result.verified_count == 1


def test_verify_manifest_rejects_changed_or_missing_artifacts_without_path_echo(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    artifact = root / "private-run" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"original")
    manifest = _write_manifest(
        tmp_path,
        [
            {
                "relative_path": "private-run/result.json",
                "sha256": hashlib.sha256(b"original").hexdigest(),
            },
            {
                "relative_path": "private-run/missing.json",
                "sha256": hashlib.sha256(b"missing").hexdigest(),
            },
        ],
    )
    artifact.write_bytes(b"changed")

    with pytest.raises(ArtifactVerificationError, match="artifact hash verification failed") as exc:
        verify_manifest(root, manifest)

    assert "private-run" not in str(exc.value)


def test_verify_manifest_rejects_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    manifest = _write_manifest(
        tmp_path,
        [{"relative_path": "../outside.json", "sha256": "a" * 64}],
    )

    with pytest.raises(ArtifactVerificationError, match="invalid artifact manifest"):
        verify_manifest(root, manifest)


def test_verify_manifest_rejects_duplicate_canonical_paths(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    artifact = root / "private-run" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"result")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = _write_manifest(
        tmp_path,
        [
            {"relative_path": "private-run/result.json", "sha256": digest},
            {"relative_path": "private-run/../private-run/result.json", "sha256": digest},
        ],
    )

    with pytest.raises(ArtifactVerificationError, match="invalid artifact manifest") as exc:
        verify_manifest(root, manifest)

    assert "private-run" not in str(exc.value)


def test_verify_manifest_converts_artifact_read_errors_to_generic_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    artifact = root / "private-run" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"result")
    manifest = _write_manifest(
        tmp_path,
        [
            {
                "relative_path": "private-run/result.json",
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
    )

    def raise_read_error(path: Path) -> NoReturn:
        raise OSError("do not expose private-run")

    monkeypatch.setattr(verify_artifact_hashes, "_sha256_file", raise_read_error)

    with pytest.raises(ArtifactVerificationError, match="artifact hash verification failed") as exc:
        verify_manifest(root, manifest)

    assert "private-run" not in str(exc.value)
