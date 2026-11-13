"""Personal-data redaction primitives for retired (注销) customers.

The business key — the anonymous chain id — is always kept. Only the personal
attribute values are replaced by :data:`REDACTED_VALUE`, in every layer:

* the current dimension and every historical chain version;
* as-of time travel and the CSV export;
* the raw daily snapshot store;
* the cross-source conflict candidates and resolution trace.

The same primitives are reused by the SCD2 build so that a late-arriving
snapshot (or a manual re-ingest) can never bring a retired customer's name,
mobile or org back to life.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.algorithms.retraction import PERSONAL_ATTRIBUTE_KEYS, REDACTED_VALUE
from src.constants.retraction_status import RetractionStatus
from src.models.retraction_batch import RetractionBatch

RETRACTED_NOTE = "（客户已注销，依据中的个人信息已隐藏）"

__all__ = [
    "PERSONAL_ATTRIBUTE_KEYS",
    "REDACTED_VALUE",
    "RETRACTED_NOTE",
    "confirmed_retraction_keys",
    "is_personal",
    "mask_attributes",
    "mask_candidates",
    "mask_conflict_item",
    "mask_resolution",
    "redact_if_retracted",
]


def is_personal(attribute_key: str) -> bool:
    return attribute_key in PERSONAL_ATTRIBUTE_KEYS


def mask_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy with every personal key replaced by the retraction mask."""
    copy = dict(attributes or {})
    for key in PERSONAL_ATTRIBUTE_KEYS:
        if key in copy:
            copy[key] = REDACTED_VALUE
    return copy


def mask_candidates(attribute_key: str, candidates: Sequence[dict] | None) -> list[dict]:
    """Mask personal candidate payloads; structural fields stay auditable."""
    rows = list(candidates or [])
    if not is_personal(attribute_key):
        return rows
    return [{**row, "value": REDACTED_VALUE, "canonical": REDACTED_VALUE} for row in rows]


def mask_resolution(attribute_key: str, resolution: dict | None) -> dict:
    """Mask the personal value of a resolution while keeping the audit trail."""
    copy = dict(resolution or {})
    if not is_personal(attribute_key):
        return copy
    if "value" in copy:
        copy["value"] = REDACTED_VALUE
    if "display_value" in copy:
        copy["display_value"] = REDACTED_VALUE
    if copy.get("note"):
        copy["note"] = RETRACTED_NOTE
    return copy


def mask_conflict_item(
    attribute_key: str, candidates: Sequence[dict] | None, resolution: dict | None
) -> tuple[list[dict], dict]:
    return mask_candidates(attribute_key, candidates), mask_resolution(attribute_key, resolution)


def redact_if_retracted(attributes: dict[str, Any] | None, business_key: str, retracted_keys: Iterable[str]) -> dict[str, Any]:
    """Read-path guard: hide personal values when the key is retired."""
    payload = dict(attributes or {})
    if business_key in retracted_keys:
        payload = mask_attributes(payload)
    return payload


def confirmed_retraction_keys(db: Session) -> set[str]:
    """Business keys whose retraction has been confirmed (personal fields hidden)."""
    rows = db.execute(
        select(RetractionBatch.business_key).where(RetractionBatch.status == RetractionStatus.CONFIRMED.value)
    ).scalars().all()
    return set(rows)
