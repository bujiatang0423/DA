from datetime import datetime
from pydantic import BaseModel, ConfigDict
class ContractModel(BaseModel): model_config=ConfigDict(extra="forbid")
def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError("timezone-aware datetime required")
    return value
