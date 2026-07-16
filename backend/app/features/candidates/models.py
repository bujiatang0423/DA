from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from backend.app.contracts.grades import DataGrade,LlmGrade
from backend.app.core.portfolio.models import StrategyBook
from backend.app.core.strategy.reason_codes import ReasonCode
class CandidateBucket(StrEnum): EXECUTABLE="executable"; WATCHLIST="watchlist"; EXCLUDED="excluded"
class CandidateState(StrEnum): UNSELECTED="unselected"; SELECTED="selected"; BREAKOUT="breakout"; PULLBACK="pullback"; STRENGTHENED="strengthened"; PENDING_EXECUTION="pending_execution"; HELD="held"
@dataclass(frozen=True,slots=True)
class CandidateFactors: p:Decimal; f:Decimal; r:Decimal; t:Decimal; v:Decimal; s:Decimal; percentile_rank:Decimal
@dataclass(frozen=True,slots=True)
class CandidateItem:
    security_id:str; security_name:str; bucket:CandidateBucket; state:CandidateState; strategy_book:StrategyBook|None; factors:CandidateFactors; planned_quantity:int; initial_stop:Decimal|None; trigger_condition:str; invalidation_condition:str; reason_codes:tuple[ReasonCode,...]; quality_codes:tuple[str,...]; evidence_refs:tuple[str,...]
@dataclass(frozen=True,slots=True)
class CandidateRecommendationResult:
    run_id:str; as_of_time:datetime; strategy_version:Literal["v2.12"]; manifest_hash:str; data_grade:DataGrade; llm_grade:LlmGrade; market_state:str; market_confidence:str; quality_codes:tuple[str,...]; items:tuple[CandidateItem,...]; auto_trade_enabled:bool=False; human_confirm_required:bool=True
    @property
    def executable(self)->tuple[CandidateItem,...]: return tuple(i for i in self.items if i.bucket is CandidateBucket.EXECUTABLE)
    @property
    def watchlist(self)->tuple[CandidateItem,...]: return tuple(i for i in self.items if i.bucket is CandidateBucket.WATCHLIST)
    @property
    def excluded(self)->tuple[CandidateItem,...]: return tuple(i for i in self.items if i.bucket is CandidateBucket.EXCLUDED)
