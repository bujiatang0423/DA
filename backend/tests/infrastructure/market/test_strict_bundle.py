import json
import shutil
from pathlib import Path

import pytest

from backend.app.infrastructure.market.strict_bundle import PitBundleError, PitBundleManifest


@pytest.fixture
def pit_bundle(tmp_path: Path) -> Path:
    source = Path(__file__).parents[2] / "fixtures" / "pit_bundle"
    destination = tmp_path / "pit_bundle"
    shutil.copytree(source, destination)
    return destination


def test_bundle_requires_every_strict_dataset(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "bundle_id": "bad", "files": []}),
        encoding="utf-8",
    )

    with pytest.raises(PitBundleError, match="missing required datasets"):
        PitBundleManifest.load(tmp_path)


def test_bundle_rejects_checksum_mismatch(pit_bundle: Path) -> None:
    manifest_path = pit_bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PitBundleError, match="checksum mismatch"):
        PitBundleManifest.load(pit_bundle)


def test_bundle_rejects_file_path_outside_its_root(pit_bundle: Path) -> None:
    manifest_path = pit_bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PitBundleError, match="bundle file escapes root"):
        PitBundleManifest.load(pit_bundle)


def test_verified_source_requires_source_and_license_ids(pit_bundle: Path) -> None:
    bundle = PitBundleManifest.load(pit_bundle)

    assert all(item.source_id and item.license_id for item in bundle.files)


def test_bundle_records_coverage_and_deterministic_manifest_digest(pit_bundle: Path) -> None:
    first = PitBundleManifest.load(pit_bundle)
    manifest_path = pit_bundle / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"].reverse()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    second = PitBundleManifest.load(pit_bundle)

    assert first.coverage_start.isoformat() == "2020-01-01"
    assert first.coverage_end.isoformat() == "2020-12-31"
    assert first.manifest_sha256 == second.manifest_sha256
