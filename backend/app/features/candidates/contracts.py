from datetime import datetime
from pydantic import BaseModel, ConfigDict
class CandidateSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of_time: datetime
