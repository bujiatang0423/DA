from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

class StrategyIntegrityError(RuntimeError): pass
@dataclass(frozen=True)
class FrozenStrategy:
    version: str; path: Path; sha256: str; text: str
class StrategyRegistry:
    def __init__(self, entries: dict[str, tuple[Path,str]]) -> None: self._entries=entries
    @classmethod
    def from_entries(cls, entries: dict[str, tuple[Path,str]]) -> "StrategyRegistry": return cls(entries)
    @classmethod
    def from_manifest(cls, path: Path) -> "StrategyRegistry":
        payload: dict[str,Any]=json.loads(path.read_text(encoding="utf-8")); return cls({v:(Path(i["path"]),i["sha256"]) for v,i in payload["strategies"].items()})
    def load(self, version: str) -> FrozenStrategy:
        try: path,expected=self._entries[version]
        except KeyError as exc: raise StrategyIntegrityError(f"unknown strategy version: {version}") from exc
        raw=path.read_bytes(); actual=sha256(raw).hexdigest()
        if actual!=expected: raise StrategyIntegrityError(f"strategy hash mismatch for {version}")
        return FrozenStrategy(version,path,actual,raw.decode("utf-8"))
