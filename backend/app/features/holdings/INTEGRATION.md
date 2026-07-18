# Holding Analysis Integration

The integration coordinator must:

1. Import holdings ORM metadata and generate holding tables in the plan-06 migration.
2. Construct `HoldingAnalysisService` with PIT, the portfolio reader, `StrategyInputBuilder`,
   `V212StrategyEngine`, and the holding repository.
3. Inject `PortfolioWriter` into the portfolio router and verify optimistic-version conflicts.
4. Call `build_holding_feature()` in the global feature registry.
5. Export OpenAPI and regenerate `web/src/generated/schema.d.ts` twice, confirming the second run
   is clean.
6. Register `holdingsFeature` in global navigation.
7. Run E2E checks for legacy display, audited correction, actual fill, async analysis, persisted result,
   and restart.
8. Confirm logs exclude position notes, source paths, API secrets, and raw LLM input or
   output.
