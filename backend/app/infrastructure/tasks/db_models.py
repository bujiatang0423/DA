from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.persistence.models import Base


class WorkerLeaseRow(Base):
    __tablename__ = "worker_leases"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
