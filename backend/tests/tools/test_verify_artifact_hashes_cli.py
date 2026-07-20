from __future__ import annotations

from pathlib import Path

from tools import verify_artifact_hashes


def test_artifact_verification_cli_does_not_echo_exception_text(
    capsys: object,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    def raise_sensitive_error(artifact_root: Path, manifest_path: Path) -> object:
        raise verify_artifact_hashes.ArtifactVerificationError("secret artifact path")

    monkeypatch.setattr(verify_artifact_hashes, "verify_manifest", raise_sensitive_error)

    assert (
        verify_artifact_hashes.main(
            [
                "--artifact-root",
                str(tmp_path / "artifacts"),
                "--manifest",
                str(tmp_path / "manifest.json"),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "artifact hash verification failed\n"
