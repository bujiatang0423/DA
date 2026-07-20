# DA Release Checklist

Record the command output, commit SHA, operator, and timestamp for each release candidate.

- `python -m tools.audit_release` returns no findings.
- `make verify` completes against the local PostgreSQL test database.
- `python -m pytest backend/tests/security backend/tests/system/test_release_audit.py -q` passes.
- `python -m alembic upgrade head` completes before the application and worker are started.
- `python -m tools.check_openapi` and `git diff --exit-code -- contracts/openapi.json` pass.
- Artifact manifests are verified with `python -m tools.verify_artifact_hashes` before restore.
- A legacy import, when authorized, records its batch id, source hashes, and quality report without
  modifying the source directory.
- Browser acceptance covers candidate review, holding analysis, legacy import, and research backtests.

No release may claim strategy effectiveness from research results. Only a result with retained
`pit_verified` evidence and the configured out-of-sample gates can support that claim.
