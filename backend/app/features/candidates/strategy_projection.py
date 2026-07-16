from decimal import Decimal
from backend.app.core.strategy.types import SecurityEvaluation
from .models import *
def project_security(value:SecurityEvaluation)->CandidateItem:
    f=value.factors or type("F",(),{"p":0,"f":0,"r":0,"t":0,"v":0,"s":0,"percentile":0})()
    bucket=CandidateBucket.EXCLUDED if value.quality_codes or not value.constraint.allowed else CandidateBucket.EXECUTABLE if value.sizing and value.sizing.quantity else CandidateBucket.WATCHLIST
    state=CandidateState.HELD if value.held else CandidateState.PENDING_EXECUTION if bucket is CandidateBucket.EXECUTABLE else CandidateState.SELECTED
    factors = CandidateFactors(
        *(Decimal(str(getattr(f, x))) for x in ("p", "f", "r", "t", "v", "s", "percentile"))
    )
    return CandidateItem(
        value.security_id, value.name, bucket, state, None, factors,
        value.sizing.quantity if value.sizing else 0,
        Decimal(str(value.sizing.initial_stop)) if value.sizing else None,
        "next session trigger", "risk or market invalidation", value.reasons,
        value.quality_codes, (),
    )
