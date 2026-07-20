"""Verify filesystem artifacts against a JSON manifest exported from PostgreSQL."""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.infrastructure.persistence.artifact_paths import (
    UnsafeArtifactPath,
    resolve_artifact,
)


class ArtifactVerificationError(ValueError):
    """Raised when a manifest is invalid or does not match the artifact store."""


@dataclass(frozen=True)
class ArtifactVerificationResult:
    expected_count: int
    verified_count: int


def verify_manifest(artifact_root: Path, manifest_path: Path) -> ArtifactVerificationResult:
    """Fail closed unless every manifest entry names a matching regular file."""
    entries = _read_manifest(manifest_path)
    seen_paths: set[Path] = set()
    verified_count = 0
    verification_failed = False

    for relative_path, expected_hash in entries:
        try:
            artifact_path = resolve_artifact(artifact_root, relative_path)
        except (OSError, UnsafeArtifactPath) as exc:
            raise ArtifactVerificationError("invalid artifact manifest") from exc

        if artifact_path in seen_paths:
            raise ArtifactVerificationError("invalid artifact manifest")
        seen_paths.add(artifact_path)
        try:
            hash_matches = artifact_path.is_file() and _sha256_file(artifact_path) == expected_hash
        except OSError:
            hash_matches = False
        if not hash_matches:
            verification_failed = True
            continue
        verified_count += 1

    if verification_failed:
        raise ArtifactVerificationError("artifact hash verification failed")
    return ArtifactVerificationResult(len(entries), verified_count)


def _read_manifest(manifest_path: Path) -> list[tuple[str, str]]:
    try:
        value: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError("invalid artifact manifest") from exc
    if not isinstance(value, list):
        raise ArtifactVerificationError("invalid artifact manifest")

    entries: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ArtifactVerificationError("invalid artifact manifest")
        relative_path = item.get("relative_path")
        digest = item.get("sha256")
        if (
            not isinstance(relative_path, str)
            or not isinstance(digest, str)
            or not _is_sha256(digest)
        ):
            raise ArtifactVerificationError("invalid artifact manifest")
        entries.append((relative_path, digest))
    return entries


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify DA artifact hashes from a JSON manifest")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        result = verify_manifest(args.artifact_root, args.manifest)
    except ArtifactVerificationError:
        print("artifact hash verification failed", file=sys.stderr)
        return 1
    print(f"verified artifact hashes: {result.verified_count}/{result.expected_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
