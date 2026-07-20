# Candidate Feature Integration

The candidate feature is manual-only. Its structured recommendation is an advisory projection and
must never be converted into an order by the Web client or worker.

The integration coordinator must:

1. import feature SQLAlchemy metadata and generate candidate tables in one plan-06 Alembic revision;
2. construct `CandidateService` with PIT warehouse, portfolio reader, `StrategyInputBuilder`,
   `V212StrategyEngine`, and repository;
3. call `build_candidate_feature()` from the global feature registry;
4. export OpenAPI, regenerate `web/src/generated/schema.d.ts`, and confirm no diff after a second
   generation;
5. register `candidateFeature` in global Web navigation;
6. run the candidate API, worker, PostgreSQL, and Web E2E path.

Provider composition is outside this feature. A missing point-in-time input must remain fail-closed
and cannot create a synthetic executable recommendation.
