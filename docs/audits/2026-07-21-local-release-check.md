# Local Release Check

The local release check is a Docker-free, two-pass smoke gate for the security and contract
surface. Run it from the repository root with:

```bash
python -m tools.verify_local_release
```

Each pass runs the release-audit and independent-path pytest tests, the runtime audit, OpenAPI
export, and a clean diff check for `contracts/openapi.json`. Both passes must complete; any
non-zero command blocks release. PostgreSQL integration, browser E2E, and external provider
availability remain separate gates. When PostgreSQL is already running locally, add
`--postgres` to run the marked backend tests against `127.0.0.1:5432`; `--passes=1` is available
for a quick smoke check, while the default remains two passes. Add `--e2e` to run the Playwright
flow in `web` during each pass.
