from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


REQUIRED_DATASETS = frozenset(
    {
        "security_master_history",
        "security_status_daily",
        "trading_calendar",
        "daily_bars_raw",
        "index_daily_bars",
        "market_breadth",
        "corporate_actions",
        "adjustment_factors",
        "industry_membership_history",
        "theme_membership_history",
        "financial_disclosures",
        "financial_facts",
        "policy_documents",
        "fee_schedules",
    }
)


class PitBundleError(ValueError):
    pass


@dataclass(frozen=True)
class PitBundleFile:
    dataset: str
    path: Path
    sha256: str
    row_count: int
    source_id: str
    license_id: str


@dataclass(frozen=True)
class PitBundleManifest:
    schema_version: int
    bundle_id: str
    coverage_start: date
    coverage_end: date
    files: tuple[PitBundleFile, ...]
    manifest_sha256: str

    def file(self, dataset: str) -> PitBundleFile:
        for item in self.files:
            if item.dataset == dataset:
                return item
        raise PitBundleError(f"dataset not found: {dataset}")

    @classmethod
    def load(cls, root: Path) -> PitBundleManifest:
        resolved_root = root.resolve()
        manifest_path = resolved_root / "manifest.json"
        raw = manifest_path.read_bytes()
        payload = json.loads(raw)
        if payload.get("schema_version") != 1:
            raise PitBundleError("unsupported schema_version")

        entries: list[PitBundleFile] = []
        datasets: set[str] = set()
        for item in payload.get("files", []):
            dataset = str(item["dataset"])
            if dataset not in REQUIRED_DATASETS:
                raise PitBundleError(f"unsupported dataset: {dataset}")
            if dataset in datasets:
                raise PitBundleError(f"duplicate dataset: {dataset}")
            datasets.add(dataset)

            path = (resolved_root / str(item["path"])).resolve()
            if path.parent != resolved_root:
                raise PitBundleError("bundle file escapes root")
            if not item.get("source_id") or not item.get("license_id"):
                raise PitBundleError("verified source requires source_id and license_id")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise PitBundleError(f"checksum mismatch: {dataset}")
            entries.append(
                PitBundleFile(
                    dataset=dataset,
                    path=path,
                    sha256=actual,
                    row_count=int(item["row_count"]),
                    source_id=str(item["source_id"]),
                    license_id=str(item["license_id"]),
                )
            )

        missing = REQUIRED_DATASETS - datasets
        if missing:
            raise PitBundleError(f"missing required datasets: {','.join(sorted(missing))}")

        coverage_start = date.fromisoformat(str(payload["coverage_start"]))
        coverage_end = date.fromisoformat(str(payload["coverage_end"]))
        if coverage_start > coverage_end:
            raise PitBundleError("coverage_start must not be after coverage_end")
        canonical_payload = dict(payload)
        canonical_payload["files"] = sorted(payload["files"], key=lambda item: str(item["dataset"]))
        canonical_raw = json.dumps(
            canonical_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        return cls(
            schema_version=1,
            bundle_id=str(payload["bundle_id"]),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            files=tuple(sorted(entries, key=lambda entry: entry.dataset)),
            manifest_sha256=hashlib.sha256(canonical_raw).hexdigest(),
        )
