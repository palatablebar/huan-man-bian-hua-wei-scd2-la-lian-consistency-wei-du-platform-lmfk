"""Customer deregistration (retraction) batch.

One batch per customer business key. Lifecycle:
``pending`` (impact manifest generated, nothing hidden yet) ->
``confirmed`` (personal fields hidden in current dimension / as-of / export / history)
or ``failed`` (redaction was rolled back to the last usable version).

The business key itself (the anonymous chain id) is never removed, and no
``dim_customers`` / ``conflict_items`` / ``customer_snapshots`` / ``audit_logs``
row is ever deleted — only the personal attributes are redacted.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class RetractionBatch(Base):
    __tablename__ = "retraction_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Natural key: 同一客户的同一撤回重复执行只会复用这一行。
    business_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    impact: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    requested_by: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    notes: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
