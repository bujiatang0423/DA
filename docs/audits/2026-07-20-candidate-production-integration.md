# Candidate Production Integration Audit

## Scope

This audit covers Candidate Integration Tasks 1-3 only. It does not claim a real candidate
recommendation, replay, or automatic-trading capability.

## Implemented Composition Seam

`build_components()` remains the single composition root. In production-provider mode it now loads
`DA_RESEARCH_PROVIDER_FACTORY` as `module.path:callable`. The callable must return
`ProductionResearchProviders` with a market, policy, and LLM port. Only then does the application
construct the one `ResearchEvidenceSource` chain used unchanged by both candidate and holding
services.

Missing, malformed, or failing factory configuration returns `UnavailableResearchWarehouse`.
That warehouse emits stable `REQUIRED_DATASET_MISSING` quality errors and cannot produce executable
candidates. The exception body, configuration string, credentials, and upstream response are not
placed in the quality detail.

The existing explicit fake-warehouse seam remains test-only. Production continues to reject fake
mode and injected provider SDK modules.

## Blocking Gaps

Candidate Integration Tasks 2 and 3 remain incomplete. Main contains evidence adapters and port
protocols, but no concrete production implementations for:

- `ResearchMarketDataPort` with PIT universe, status, financial, and market datasets;
- `OfficialPolicyClient` backed by the required official normalized policy feed; and
- `LlmFactorPort` backed by a configured structured-factor client.

The former AkShare/BaoStock daily-bar source is intentionally retained only as a test seam. It is
not a complete `ResearchMarketDataPort` and must not be treated as a production candidate source.

Once Provider Tasks 5-8 deliver those concrete ports, deployment can configure the factory without
changing candidate orchestration. A full factory integration test must then verify source lineage,
PIT availability, invalid-provider failure, and a non-executable empty result for every missing
input.
