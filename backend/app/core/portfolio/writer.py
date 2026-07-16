from dataclasses import asdict
from datetime import datetime, timezone
import hashlib,json
from backend.app.core.portfolio.models import PortfolioSnapshot
from backend.app.ports.portfolio import ConcurrentPortfolioUpdate
class AuditedPortfolioWriter:
    def __init__(self, store:object)->None:self._store=store
    def record_manual_fill(self, command:object, expected_version:int)->PortfolioSnapshot:
        event=type('AuditEvent',(),{'event_type':'manual_fill','expected_version':expected_version,'reason':'用户录入真实成交'})()
        return self._store.append(event=event,payload=command,expected_version=expected_version)
    def replace_positions_for_correction(self,snapshot:object,expected_version:int,reason:str)->PortfolioSnapshot:
        if not reason.strip(): raise ValueError('correction reason is required')
        event=type('AuditEvent',(),{'event_type':'position_correction','expected_version':expected_version,'reason':reason.strip()})()
        return self._store.append(event=event,payload=snapshot,expected_version=expected_version)
