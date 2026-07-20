# Local Backup And Recovery Runbook

This runbook is for a locally operated PostgreSQL DA deployment. It does not use Docker.
Run it from a trusted local shell. Do not paste passwords, database URLs, request payloads, or
artifact contents into a terminal transcript, ticket, or source control.

## Prerequisites

Install PostgreSQL client tools compatible with the server: `pg_dump`, `pg_restore`, `psql`, and
`shasum`. Configure local authentication with a mode-0600 `~/.pgpass` file, or use an interactive
password prompt. Export non-secret connection fields only:

```bash
export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=da
export PGDATABASE=da
export DA_ARTIFACT_ROOT="$PWD/data/artifacts"
```

Use a dated backup directory outside the repository and keep its permissions private:

```bash
umask 077
export BACKUP_DIR="$HOME/da-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
```

## Backup

Pause the API and worker first so a restore point has a documented operational boundary. The
database dump itself is transactionally consistent; stopping the processes prevents the artifact
filesystem and database metadata from diverging while the two archives are made.

```bash
./scripts/start.sh stop

export DUMP_NAME=da.dump
pg_dump --format=custom --no-owner --no-privileges --file "$BACKUP_DIR/$DUMP_NAME" "$PGDATABASE"
pg_restore --list "$BACKUP_DIR/$DUMP_NAME" >/dev/null

(
    cd "$BACKUP_DIR"
    shasum -a 256 "$DUMP_NAME" > "$DUMP_NAME.sha256"
)
```

Export the authoritative run-artifact manifest from the same database. The command emits only
relative filesystem paths and SHA-256 values, and never artifact content or database credentials.

```bash
export MANIFEST_NAME=run-artifacts.json
psql --no-psqlrc -X --set ON_ERROR_STOP=1 --tuples-only --no-align \
    --command "SELECT COALESCE(jsonb_agg(jsonb_build_object( \
        'relative_path', relative_path, 'sha256', sha256) ORDER BY relative_path), '[]'::jsonb) \
        FROM run_artifacts;" > "$BACKUP_DIR/$MANIFEST_NAME"

export ARTIFACT_ARCHIVE_NAME=artifacts.tar
tar --create --file "$BACKUP_DIR/$ARTIFACT_ARCHIVE_NAME" --directory "$DA_ARTIFACT_ROOT" .
(
    cd "$BACKUP_DIR"
    shasum -a 256 "$MANIFEST_NAME" "$ARTIFACT_ARCHIVE_NAME" > artifacts.sha256
)
```

Verify before retaining the backup. A nonzero status means the backup must not be used for
recovery until the discrepancy is understood and a fresh backup is made.

```bash
(
    cd "$BACKUP_DIR"
    shasum -a 256 -c "$DUMP_NAME.sha256"
    shasum -a 256 -c artifacts.sha256
)
python -m tools.verify_artifact_hashes \
    --artifact-root "$DA_ARTIFACT_ROOT" \
    --manifest "$BACKUP_DIR/$MANIFEST_NAME"
```

Only restart deliberately after verification:

```bash
./scripts/start.sh start
```

## Recovery

Never restore over a live production database. Stop the API and worker, preserve the failed data
directory for investigation, and have the database owner provision an empty local recovery
database. Point `PGDATABASE` at that recovery database only after its name has been reviewed.

First verify the copied backup files. Do not extract or restore a backup that fails either check.

```bash
(
    cd "$BACKUP_DIR"
    shasum -a 256 -c "$DUMP_NAME.sha256"
    shasum -a 256 -c artifacts.sha256
)
pg_restore --list "$BACKUP_DIR/$DUMP_NAME" >/dev/null
```

Restore database metadata and artifacts to empty recovery locations. `RECOVERY_ARTIFACT_ROOT`
must not be the active artifact directory.

```bash
./scripts/start.sh stop

export PGDATABASE=da_recovery
pg_restore --no-owner --no-privileges --dbname "$PGDATABASE" "$BACKUP_DIR/$DUMP_NAME"

export RECOVERY_ARTIFACT_ROOT="$PWD/data/artifacts-recovery"
mkdir -p "$RECOVERY_ARTIFACT_ROOT"
tar --extract --file "$BACKUP_DIR/$ARTIFACT_ARCHIVE_NAME" --directory "$RECOVERY_ARTIFACT_ROOT"
python -m tools.verify_artifact_hashes \
    --artifact-root "$RECOVERY_ARTIFACT_ROOT" \
    --manifest "$BACKUP_DIR/$MANIFEST_NAME"
```

Confirm the restored schema before starting any service. DA reads its configured URL through the
`DA_DATABASE_URL` setting; set that setting through the local secret mechanism rather than placing
credentials in shell history. Apply migrations only after reviewing the reported revision.

```bash
read -r -s DA_DATABASE_URL
export DA_DATABASE_URL
printf '\n'
python -m alembic current
unset DA_DATABASE_URL
```

After the schema revision, artifact verification, and application configuration are independently
reviewed, start the API before starting a worker. Check readiness locally and inspect only
structured operational status; do not replay queued runs automatically as part of recovery.

```bash
python -m backend.app.main
curl --fail --silent http://127.0.0.1:8000/api/v1/health/ready
python -m backend.app.worker_main
```

Record the backup timestamp, dump hash, artifact archive hash, manifest hash, restore target, and
the verification result in the operational change record. Do not record passwords, connection
URLs, artifact paths, payloads, or user data.
