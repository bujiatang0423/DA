from __future__ import annotations

import pytest
from datetime import UTC, datetime

from backend.app.core.market.pit_models import DataKind, SnapshotScope


def test_strict_backtest_scope_only_requests_certifiable_persisted_inputs() -> None:
    scope = SnapshotScope.backtest((), history_start=datetime(2020, 1, 1, tzinfo=UTC))

    assert DataKind.LLM_FACTOR not in scope.required_kinds
    assert DataKind.REALTIME_QUOTE not in scope.required_kinds
    assert {
        DataKind.SECURITY_MASTER,
        DataKind.SECURITY_STATUS,
        DataKind.TRADING_CALENDAR,
        DataKind.DAILY_BAR_RAW,
        DataKind.INDEX_DAILY_BAR,
        DataKind.FEE_SCHEDULE,
    }.issubset(scope.required_kinds)


def test_local_e2e_harness_requires_an_explicit_test_only_switch() -> None:
    from backend.app.bootstrap.e2e import E2EConfigurationError, require_local_e2e_mode

    with pytest.raises(E2EConfigurationError, match="DA_E2E_LOCAL"):
        require_local_e2e_mode({})

    require_local_e2e_mode({"DA_E2E_LOCAL": "1", "DA_ENVIRONMENT": "test"})


def test_local_e2e_harness_rejects_non_test_environment() -> None:
    from backend.app.bootstrap.e2e import E2EConfigurationError, require_local_e2e_mode

    with pytest.raises(E2EConfigurationError, match="test environment"):
        require_local_e2e_mode({"DA_E2E_LOCAL": "1", "DA_ENVIRONMENT": "production"})
