from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
class LegacyQualityTag(StrEnum):
    MISSING_ARCHIVE='missing_archive'; CHECKSUM_MISMATCH='checksum_mismatch'; UNINDEXED_FILE='unindexed_file'; BUY_DATE_AFTER_SNAPSHOT='buy_date_after_snapshot'
@dataclass(frozen=True)
class LegacyFileInspection: path:Path; sha256:str; snapshot_at:datetime|None; tags:tuple[LegacyQualityTag,...]
@dataclass(frozen=True)
class LegacyInspectionReport: source_root:Path; files:tuple[LegacyFileInspection,...]; tags:tuple[LegacyQualityTag,...]
@dataclass(frozen=True)
class LegacyPositionRow:
    security_id:str; name:str; asset_type:str; industry:str; quantity:int; inherited_unit_cost:Decimal; imported_buy_date:date|None; highest_price_since_buy:Decimal|None; notes:str; source_row_number:int
