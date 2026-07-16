from datetime import datetime
from typing import Literal
from pydantic import Field, field_validator
from .common import ContractModel, require_aware
from .grades import DataGrade,LlmGrade
class StrategyVersion(ContractModel): version:str=Field(pattern=r"^v\d+\.\d+$"); sha256:str=Field(pattern=r"^[0-9a-f]{64}$")
class AsOf(ContractModel):
    as_of_time:datetime; timezone:Literal["Asia/Shanghai"]="Asia/Shanghai"; data_grade:DataGrade=DataGrade.RESEARCH; llm_grade:LlmGrade=LlmGrade.NOT_USED
    _aware=field_validator("as_of_time")(require_aware)
