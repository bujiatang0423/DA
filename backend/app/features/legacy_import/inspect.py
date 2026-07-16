import csv,hashlib,json
from datetime import date,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .models import LegacyFileInspection,LegacyInspectionReport,LegacyQualityTag
def _sha256(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def _snapshot_at(p:Path)->datetime|None:
    try:return datetime.strptime(p.name[:15],'%Y-%m-%d_%H%M').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    except ValueError:return None
def inspect_source(source_root:Path)->LegacyInspectionReport:
    root=source_root.resolve(); history=root/'data'/'holdings'/'历史持仓'; index_path=history/'index.json'; index=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
    actual={p.name:p for p in history.glob('*.csv')}; indexed={Path(str(e.get('archive',''))).name for e in index}; files=[]; tags=set()
    for e in index:
        name=Path(str(e.get('archive',''))).name; p=actual.get(name)
        if p is None: tags.add(LegacyQualityTag.MISSING_ARCHIVE); continue
        t=set(); digest=_sha256(p)
        if digest!=e.get('sha256'): t.add(LegacyQualityTag.CHECKSUM_MISMATCH)
        snap=_snapshot_at(p)
        if snap:
            with p.open(encoding='utf-8-sig',newline='') as f:
                if any(r.get('buy_date') and date.fromisoformat(r['buy_date'])>snap.date() for r in csv.DictReader(f)): t.add(LegacyQualityTag.BUY_DATE_AFTER_SNAPSHOT)
        files.append(LegacyFileInspection(p,digest,snap,tuple(sorted(t)))); tags.update(t)
    for name,p in actual.items():
        if name not in indexed: files.append(LegacyFileInspection(p,_sha256(p),_snapshot_at(p),(LegacyQualityTag.UNINDEXED_FILE,))); tags.add(LegacyQualityTag.UNINDEXED_FILE)
    return LegacyInspectionReport(root,tuple(sorted(files,key=lambda x:str(x.path))),tuple(sorted(tags)))
