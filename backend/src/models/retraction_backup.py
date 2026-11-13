"""Original payloads captured before a retraction redacts personal fields.

Rows are kept so a failed retraction can restore the last usable version
without deleting anonymous chain ids or touching audit counters.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class RetractionBackup(Base):
    __tablename__ = "retraction_backups"
    __table_args__ = (
        UniqueConstraint("retraction_id", "entity_type", "row_id", name="uq_retraction_backup_row"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    retraction_id: Mapped[int] = mapped_column(ForeignKey("retraction_batches.id"), nullable=False, index=True)
    # dim_row | snapshot_row | conflict_item
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    row_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
