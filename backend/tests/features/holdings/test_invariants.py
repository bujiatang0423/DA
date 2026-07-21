from dataclasses import asdict
from pathlib import Path

from backend.app.features.holdings.service import HoldingAnalysisCommand
from backend.tests.features.holdings.test_service import build_service


def test_analysis_does_not_mutate_portfolio_lots() -> None:
    service, command, _, portfolios, *_ = build_service()
    lot = portfolios.snapshot_value.lots[0]
    before = asdict(lot)

    service.run(command)

    assert asdict(lot) == before


def test_same_manifest_and_portfolio_produce_identical_advice() -> None:
    service, command, *_ = build_service()

    first = service.run(command)
    second = service.run(
        HoldingAnalysisCommand("holding-run-service-repeat", command.portfolio_id, command.as_of_time)
    )

    assert first.items == second.items


def test_feature_has_no_markdown_parser_or_la_runtime_dependency() -> None:
    files = Path("backend/app/features/holdings").glob("*.py")
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "parse_markdown" not in source
    assert "/Users/bujiatang/workspace/LA" not in source
    assert "auto_trade_enabled=True" not in source
