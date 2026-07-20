# Local Backup And Recovery Runbook

This runbook is for a locally operated PostgreSQL DA deployment. It does not use Docker.
Run it from a trusted local shell. Do not paste passwords, database URLs, request payloads, or
artifact contents into a terminal transcript, ticket, or source control.

## Prerequisites

Install PostgreSQL client tools compatible with the server: `pg_dump`, `pg_restore`, `psql`, and
`shasum`. Configure local authentication with a mode-0600 `~/.pgpass` file, or use an interactive
password prompt. Keep the reviewed application configuration in `DA_DATABASE_URL`; do not replace
it with a guessed host, port, user, or database name.

```bash
export DA_ARTIFACT_ROOT="$PWD/data/artifacts"
test -n "${DA_DATABASE_URL:-}" || { printf '%s\n' 'DA_DATABASE_URL is required' >&2; exit 1; }
```

Use a dated backup directory outside the repository and keep its permissions private:

```bash
umask 077
export BACKUP_DIR="$HOME/da-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
```

Derive the PostgreSQL client connection fields from the reviewed application URL. This deliberately
does not export a password, so authentication remains in `.pgpass` or the interactive prompt. The
generated file has private permissions because it identifies the local database target.

```bash
set -e
python - <<'PY' > "$BACKUP_DIR/postgres-connection.env"
import os
import shlex
from urllib.parse import unquote, urlsplit

url = urlsplit(os.environ["DA_DATABASE_URL"])
database = unquote(url.path.lstrip("/"))
if not url.scheme.startswith("postgresql") or not url.hostname or not database:
    raise SystemExit("DA_DATABASE_URL must identify a PostgreSQL database")
fields = {
    "PGHOST": url.hostname,
    "PGPORT": str(url.port or 5432),
    "PGUSER": unquote(url.username or os.environ.get("USER", "")),
    "PGDATABASE": database,
}
for name, value in fields.items():
    print(f"export {name}={shlex.quote(value)}")
PY
. "$BACKUP_DIR/postgres-connection.env"
```

## Backup

Pause the API and worker first so a restore point has a documented operational boundary. The
database dump itself is transactionally consistent; stopping the processes prevents the artifact
filesystem and database metadata from diverging while the two archives are made.

```bash
set -e
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
set -e
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
set -e
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
database. Configure `DA_DATABASE_URL` through the private local secret mechanism to point to that
reviewed recovery database before continuing; keep it exported through migration, API, and worker
verification. Do not set `PGDATABASE` independently.

Set the reviewed recovery database name separately so both the client fields and DA configuration
can be checked without printing a connection URL:

```bash
export EXPECTED_RECOVERY_DATABASE='reviewed-recovery-database-name'
```

First verify the copied backup files. Do not extract or restore a backup that fails either check.

```bash
set -e
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
set -e
./scripts/start.sh stop

test -n "${DA_DATABASE_URL:-}" || { printf '%s\n' 'DA_DATABASE_URL is required' >&2; exit 1; }
python - <<'PY' > "$BACKUP_DIR/postgres-connection.env"
import os
import shlex
from urllib.parse import unquote, urlsplit

url = urlsplit(os.environ["DA_DATABASE_URL"])
database = unquote(url.path.lstrip("/"))
if not url.scheme.startswith("postgresql") or not url.hostname or not database:
    raise SystemExit("DA_DATABASE_URL must identify a PostgreSQL database")
for name, value in {
    "PGHOST": url.hostname,
    "PGPORT": str(url.port or 5432),
    "PGUSER": unquote(url.username or os.environ.get("USER", "")),
    "PGDATABASE": database,
}.items():
    print(f"export {name}={shlex.quote(value)}")
PY
. "$BACKUP_DIR/postgres-connection.env"
pg_restore --no-owner --no-privileges --dbname "$PGDATABASE" "$BACKUP_DIR/$DUMP_NAME"

export RECOVERY_ARTIFACT_ROOT="$PWD/data/artifacts-recovery"
mkdir -p "$RECOVERY_ARTIFACT_ROOT"
tar --extract --file "$BACKUP_DIR/$ARTIFACT_ARCHIVE_NAME" --directory "$RECOVERY_ARTIFACT_ROOT"
python -m tools.verify_artifact_hashes \
    --artifact-root "$RECOVERY_ARTIFACT_ROOT" \
    --manifest "$BACKUP_DIR/$MANIFEST_NAME"
```

Confirm the restored schema before starting any service. DA reads its configured URL through the
`DA_DATABASE_URL` setting, including Alembic, the API, and `backend.app.worker_main`. Verify that
the reviewed recovery database name is still the one derived from that setting. Apply migrations
only after reviewing the reported revision.

```bash
set -e
test "$PGDATABASE" = "$EXPECTED_RECOVERY_DATABASE" || {
    printf '%s\n' 'PostgreSQL client target changed' >&2
    exit 1
}
test "$EXPECTED_RECOVERY_DATABASE" = "$(python - <<'PY'
from backend.app.bootstrap.settings import Settings
from urllib.parse import unquote, urlsplit

print(unquote(urlsplit(Settings().database_url).path.lstrip("/")))
PY
)" || { printf '%s\n' 'application database target changed' >&2; exit 1; }
python -m alembic current
```

After the schema revision, artifact verification, and application configuration are independently
reviewed, use a short managed API probe. It runs in the background, waits for local readiness, and
cleans up even when readiness fails. It does not start a worker or replay queued runs.

```bash
set -e
python -m backend.app.main > "$BACKUP_DIR/recovery-api.log" 2>&1 &
api_pid=$!
cleanup_api() { kill "$api_pid" 2>/dev/null || true; wait "$api_pid" 2>/dev/null || true; }
trap cleanup_api EXIT INT TERM
for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl --fail --silent http://127.0.0.1:8000/api/v1/health/ready && break
    sleep 1
done
curl --fail --silent http://127.0.0.1:8000/api/v1/health/ready
cleanup_api
trap - EXIT INT TERM
```

Start the managed API and worker only after a human has approved resuming recovered work. They
inherit the unchanged `DA_DATABASE_URL` and therefore use the same reviewed recovery database.

```bash
set -e
./scripts/start.sh start
./scripts/start.sh status
./scripts/start.sh stop
```

Record the backup timestamp, dump hash, artifact archive hash, manifest hash, restore target, and
the verification result in the operational change record. Do not record passwords, connection
URLs, artifact paths, payloads, or user data.
