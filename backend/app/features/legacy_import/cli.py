import argparse
import json
from datetime import datetime
from pathlib import Path
from backend.app.bootstrap.settings import Settings
from backend.app.infrastructure.persistence.database import build_engine, build_session_factory
from .repository import SqlLegacyRepository
from .service import LegacyImportService


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="da-legacy-import")
    p.add_argument("--source-root", required=True)
    p.add_argument("--effective-at", required=True)
    p.add_argument("--portfolio-id", required=True)
    p.add_argument("--imports-root", default="data/imports")
    return p


def main() -> int:
    args = build_parser().parse_args()
    effective_at = datetime.fromisoformat(args.effective_at)
    settings = Settings()
    engine = build_engine(settings.database_url)
    sessions = build_session_factory(engine)
    with sessions.begin() as session:
        batch = LegacyImportService(
            Path(args.imports_root), SqlLegacyRepository(session)
        ).import_source(
            source_root=Path(args.source_root),
            portfolio_id=args.portfolio_id,
            effective_at=effective_at,
        )
    print(
        json.dumps(
            {
                "batch_id": batch.batch_id,
                "effective_at": batch.effective_at.isoformat(),
                "manifest_sha256": batch.manifest_sha256,
                "idempotent": batch.idempotent,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
