from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from backend.app.contracts.grades import DataGrade, LlmGrade
from backend.app.features.candidates.models import *


def test_result_is_fail_closed() -> None:
    item = CandidateItem(
        "A",
        "A",
        CandidateBucket.EXECUTABLE,
        CandidateState.PENDING_EXECUTION,
        None,
        CandidateFactors(*(Decimal("1") for _ in range(7))),
        100,
        Decimal("9"),
        "trigger",
        "invalidate",
        (),
        (),
        (),
    )
    result = CandidateRecommendationResult(
        "r",
        datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
        "v2.12",
        "m",
        DataGrade.RESEARCH,
        LlmGrade.NOT_USED,
        "strong",
        "normal",
        (),
        (item,),
    )
    assert (
        result.auto_trade_enabled is False
        and result.human_confirm_required is True
        and result.executable == (item,)
    )
