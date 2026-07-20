from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError


@dataclass(frozen=True)
class SafeRunFailure:
    code: str
    message: str


_MESSAGES: dict[str, str] = {
    "INVALID_RUN_PAYLOAD": "任务参数无效，无法执行。",
    "PROVIDER_UNAVAILABLE": "数据源暂时不可用，请稍后重试。",
    "HOLDING_ANALYSIS_INVARIANT_VIOLATION": "持仓分析请求不满足执行条件。",
    "HOLDING_MARKET_DATA_MISSING": "持仓分析所需市场数据不可用。",
    "BACKTEST_SNAPSHOT_QUALITY_ERROR": "回测所需点时数据未通过验证。",
    "JOB_EXECUTION_FAILED": "任务执行失败，请稍后重试。",
}


def normalize_run_error_code(code: str | None) -> str:
    if code in _MESSAGES:
        return code
    return "JOB_EXECUTION_FAILED"


def safe_run_message(code: str | None) -> str | None:
    if code is None:
        return None
    return _MESSAGES[normalize_run_error_code(code)]


def classify_run_failure(error: Exception) -> SafeRunFailure:
    if isinstance(error, ValidationError):
        code = "INVALID_RUN_PAYLOAD"
    else:
        candidate_code = getattr(error, "code", None)
        code = normalize_run_error_code(candidate_code)
    return SafeRunFailure(code=code, message=_MESSAGES[code])
