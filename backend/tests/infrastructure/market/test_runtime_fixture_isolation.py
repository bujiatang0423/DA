from pathlib import Path

from backend.app.bootstrap.composition import ProviderConfigurationError, build_warehouse
from backend.app.bootstrap.settings import Settings


ROOT = Path(__file__).resolve().parents[4]


def test_normal_worker_does_not_reference_local_market_fixture() -> None:
    source = (ROOT / "backend/app/worker_main.py").read_text(encoding="utf-8")

    assert "fixtures" not in source
    assert "local_market" not in source


def test_normal_runtime_rejects_fake_candidate_and_holding_warehouse() -> None:
    settings = Settings(environment="development", provider_mode="fake")

    try:
        build_warehouse(settings, fake_warehouse=object())
    except ProviderConfigurationError:
        return
    raise AssertionError("normal runtime accepted a fake warehouse")


def test_backtest_worker_uses_strict_pit_implementation() -> None:
    source = (ROOT / "backend/app/bootstrap/backtest_worker.py").read_text(encoding="utf-8")

    assert "build_strict_pit_warehouse" in source
    assert "fixtures" not in source
