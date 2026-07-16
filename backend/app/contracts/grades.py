from enum import StrEnum
class DataGrade(StrEnum): RESEARCH="research"; PIT_VERIFIED="pit_verified"
class LlmGrade(StrEnum): NOT_USED="not_used"; RECONSTRUCTED="reconstructed"; FORWARD_OBSERVED="forward_observed"
