"""Customer retraction batches: impact manifest, confirmation, redaction and restore.

Invariants enforced here
------------------------
1. One batch per customer business key — repeated requests reuse the row, they
   never append a second batch or duplicate backup rows.
2. Creating a batch never hides data: it only records a *pending* impact
   manifest for the operator to confirm.
3. Confirming redacts personal fields (name / mobile / org) in the current
   dimension, all historical chain versions, as-of reads, CSV exports, the raw
   snapshot store and the conflict trace — never the anonymous business key,
   never the chain counters, never an audit row.
4. Originals are captured in ``retraction_backups`` *before* any mutation is
   committed. Any failure of the redaction transaction rolls every entity back
   to the last usable version (``status = failed``), and an explicit
   ``/restore`` re-applies the same rollback idempotently. On success the
   backup payloads are purged (only the idempotency marker rows stay) so no
   personal data lingers at rest.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.algorithms.retraction import (
    build_impact_manifest,
    confirmation_guard,
    count_secret_occurrences,
    late_snapshot_hidden,
    restore_snapshot,
)
from src.constants.messages import MSG_RETRACTION_NOT_FOUND, MSG_RETRACTION_NOT_RESTORABLE
from src.constants.retraction_status import RETRACTION_STATUS_LABELS, RetractionStatus
from src.models.conflict_item import ConflictItem
from src.models.customer_snapshot import CustomerSnapshot
from src.models.dim_customer import DimCustomer
from src.models.retraction_backup import RetractionBackup
from src.models.retraction_batch import RetractionBatch
from src.services import build_service, privacy
from src.utils.logger import log_event

PURGED = {"purged": True}


# --------------------------------------------------------------------------- #
# read models
# --------------------------------------------------------------------------- #
def _latest_run_id(db: Session) -> int | None:
    run = build_service.latest_run(db)
    return run.id if run else None


def _rows_for_key(
    db: Session, business_key: str
) -> tuple[list[DimCustomer], list[CustomerSnapshot], list[ConflictItem]]:
    dims = db.execute(select(DimCustomer).where(DimCustomer.business_key == business_key)).scalars().all()
    snapshots = db.execute(
        select(CustomerSnapshot).where(CustomerSnapshot.business_key == business_key)
    ).scalars().all()
    conflicts = db.execute(select(ConflictItem).where(ConflictItem.business_key == business_key)).scalars().all()
    return list(dims), list(snapshots), list(conflicts)


def _impact(db: Session, business_key: str) -> dict:
    dims, snapshots, conflicts = _rows_for_key(db, business_key)
    latest_id = _latest_run_id(db)
    if latest_id is not None:
        current_rows = [row for row in dims if row.build_run_id == latest_id and row.is_current]
    else:
        current_rows = [row for row in dims if row.is_current]
    occurrences = count_secret_occurrences([row.attributes for row in dims] + [row.attributes for row in snapshots])
    for row in conflicts:
        if privacy.is_personal(row.attribute_key):
            occurrences[row.attribute_key] = occurrences.get(row.attribute_key, 0) + len(row.candidates or [])
    return build_impact_manifest(
        business_key=business_key,
        chain_versions=len(dims),
        chain_keys={row.business_key for row in current_rows}
        or ({business_key} if dims else set()),
        snapshot_rows=len(snapshots),
        snapshot_sources=[row.source_code for row in snapshots],
        conflict_rows=len(conflicts),
        conflict_attribute_keys=[row.attribute_key for row in conflicts],
        pre_retraction_run_id=latest_id,
        secret_field_occurrences=occurrences,
    )


def batch_payload(db: Session, batch: RetractionBatch) -> dict:
    return {
        "id": batch.id,
        "business_key": batch.business_key,
        "status": batch.status,
        "status_label": RETRACTION_STATUS_LABELS.get(batch.status, batch.status),
        "impact": batch.impact or {},
        "requested_by": batch.requested_by,
        "requested_at": batch.requested_at.isoformat(sep=" ", timespec="seconds") if batch.requested_at else None,
        "confirmed_by": batch.confirmed_by,
        "confirmed_at": batch.confirmed_at.isoformat(sep=" ", timespec="seconds") if batch.confirmed_at else None,
        "attempt_count": batch.attempt_count,
        "baseline_run_id": batch.baseline_run_id,
        "applied_run_id": batch.applied_run_id,
        "restored_at": batch.restored_at.isoformat(sep=" ", timespec="seconds") if batch.restored_at else None,
        "error_message": batch.error_message,
        "notes": batch.notes,
        "personal_fields": list(privacy.PERSONAL_ATTRIBUTE_KEYS),
        "anonymous_key_preserved": True,
        "backup_rows": int(
            db.execute(
                select(func.count(RetractionBackup.id)).where(RetractionBackup.retraction_id == batch.id)
            ).scalar()
            or 0
        ),
    }


def list_batches(db: Session, status: str = "all", business_key: str = "") -> list[dict]:
    query = select(RetractionBatch)
    if status and status != "all":
        query = query.where(RetractionBatch.status == status)
    if business_key:
        query = query.where(RetractionBatch.business_key == business_key)
    rows = db.execute(query.order_by(RetractionBatch.id.desc())).scalars().all()
    return [batch_payload(db, row) for row in rows]


def summary(db: Session) -> dict:
    rows = db.execute(
        select(RetractionBatch.status, func.count(RetractionBatch.id)).group_by(RetractionBatch.status)
    ).all()
    by_status = {status: int(count) for status, count in rows}
    return {
        "total": sum(by_status.values()),
        "pending": by_status.get(RetractionStatus.PENDING.value, 0),
        "confirmed": by_status.get(RetractionStatus.CONFIRMED.value, 0),
        "failed": by_status.get(RetractionStatus.FAILED.value, 0),
        "by_status": by_status,
        "labels": RETRACTION_STATUS_LABELS,
        "personal_fields": list(privacy.PERSONAL_ATTRIBUTE_KEYS),
    }


def get_batch(db: Session, batch_id: int) -> RetractionBatch:
    row = db.get(RetractionBatch, batch_id)
    if row is None:
        raise HTTPException(status_code=404, detail=MSG_RETRACTION_NOT_FOUND)
    return row


def preview_impact(db: Session, business_key: str) -> dict:
    """Impact manifest for the confirmation screen; never persists anything."""
    business_key = (business_key or "").strip()
    if not business_key:
        raise HTTPException(status_code=422, detail="业务键不能为空")
    dims, snapshots, conflicts = _rows_for_key(db, business_key)
    if not dims and not snapshots and not conflicts:
        raise HTTPException(status_code=404, detail=MSG_RETRACTION_NOT_FOUND)
    existing = db.execute(
        select(RetractionBatch).where(RetractionBatch.business_key == business_key)
    ).scalar_one_or_none()
    return {
        "business_key": business_key,
        "impact": _impact(db, business_key),
        "existing": batch_payload(db, existing) if existing is not None else None,
    }


# --------------------------------------------------------------------------- #
# backup capture / restore
# --------------------------------------------------------------------------- #
def _has_personal(attributes: dict | None) -> bool:
    values = attributes or {}
    return any(values.get(key) not in (None, "", privacy.REDACTED_VALUE) for key in privacy.PERSONAL_ATTRIBUTE_KEYS)


def _capture_backups(db: Session, batch: RetractionBatch, business_key: str) -> dict:
    """Phase A — persist originals before anything is mutated (own transaction)."""
    dims, snapshots, conflicts = _rows_for_key(db, business_key)
    existing = {
        (row.entity_type, row.row_id)
        for row in db.execute(
            select(RetractionBackup).where(RetractionBackup.retraction_id == batch.id)
        ).scalars().all()
    }
    captured = {"dim_versions": 0, "snapshot_rows": 0, "conflict_items": 0}

    def add(entity_type: str, row_id: int, original: dict) -> None:
        if (entity_type, row_id) in existing:
            return
        db.add(RetractionBackup(retraction_id=batch.id, entity_type=entity_type, row_id=row_id, original=original))
        existing.add((entity_type, row_id))

    for row in dims:
        if _has_personal(row.attributes):
            add("dim_row", row.id, {"attributes": dict(row.attributes or {})})
            captured["dim_versions"] += 1
    for row in snapshots:
        if _has_personal(row.attributes):
            add("snapshot_row", row.id, {"attributes": dict(row.attributes or {})})
            captured["snapshot_rows"] += 1
    for row in conflicts:
        if not privacy.is_personal(row.attribute_key):
            continue
        candidates, resolution = privacy.mask_conflict_item(row.attribute_key, row.candidates, row.resolution)
        if candidates != (row.candidates or []) or resolution != (row.resolution or {}):
            add(
                "conflict_item",
                row.id,
                {"candidates": list(row.candidates or []), "resolution": dict(row.resolution or {})},
            )
            captured["conflict_items"] += 1

    db.commit()
    return captured


def _backup_payloads(db: Session, batch: RetractionBatch) -> list[RetractionBackup]:
    return (
        db.execute(
            select(RetractionBackup)
            .where(RetractionBackup.retraction_id == batch.id)
            .order_by(RetractionBackup.id)
        )
        .scalars()
        .all()
    )


def _restore_from_backups(db: Session, batch: RetractionBatch) -> dict:
    """Put every backed-up row back to its last usable version.

    Only attribute payloads are restored: rows are never deleted, so anonymous
    business keys and the chain / audit counters stay intact.
    """
    restored = {"dim_versions": 0, "snapshot_rows": 0, "conflict_items": 0}
    for backup in _backup_payloads(db, batch):
        if backup.original == PURGED:
            continue
        if backup.entity_type == "dim_row":
            row = db.get(DimCustomer, backup.row_id)
            if row is not None:
                row.attributes = dict((backup.original or {}).get("attributes") or {})
                restored["dim_versions"] += 1
        elif backup.entity_type == "snapshot_row":
            row = db.get(CustomerSnapshot, backup.row_id)
            if row is not None:
                row.attributes = dict((backup.original or {}).get("attributes") or {})
                restored["snapshot_rows"] += 1
        elif backup.entity_type == "conflict_item":
            row = db.get(ConflictItem, backup.row_id)
            if row is not None:
                row.candidates = list((backup.original or {}).get("candidates") or [])
                row.resolution = dict((backup.original or {}).get("resolution") or {})
                restored["conflict_items"] += 1
    db.commit()
    return restored


def _purge_backup_payloads(db: Session, batch: RetractionBatch) -> None:
    """Drop the captured personal values once the retraction is in force.

    Runs inside the confirmation transaction: if the final commit fails the
    originals are still there to restore from.
    """
    for backup in _backup_payloads(db, batch):
        backup.original = dict(PURGED)
    db.flush()


def _apply_redaction(db: Session, batch: RetractionBatch, business_key: str) -> dict:
    """Phase B — replace personal values in every layer, commit, then re-read.

    All chain versions of every run are mutated in place (never deleted), so the
    anonymous business key, the chain counters and the audit rows are untouched.
    """
    dims, snapshots, conflicts = _rows_for_key(db, business_key)
    counts = {"dim_versions": 0, "snapshot_rows": 0, "conflict_items": 0}
    for row in dims:
        if _has_personal(row.attributes):
            row.attributes = privacy.mask_attributes(row.attributes)
            counts["dim_versions"] += 1
    for row in snapshots:
        if _has_personal(row.attributes):
            row.attributes = privacy.mask_attributes(row.attributes)
            counts["snapshot_rows"] += 1
    for row in conflicts:
        if not privacy.is_personal(row.attribute_key):
            continue
        candidates, resolution = privacy.mask_conflict_item(row.attribute_key, row.candidates, row.resolution)
        if candidates != (row.candidates or []) or resolution != (row.resolution or {}):
            row.candidates = candidates
            row.resolution = resolution
            counts["conflict_items"] += 1
    db.commit()
    return counts


# --------------------------------------------------------------------------- #
# public commands
# --------------------------------------------------------------------------- #
def create_batch(db: Session, business_key: str, *, actor_email: str, notes: str = "") -> dict:
    """Create (or reuse) the pending batch and regenerate its impact manifest."""
    business_key = (business_key or "").strip()
    if not business_key:
        raise HTTPException(status_code=422, detail="业务键不能为空")

    dims, snapshots, conflicts = _rows_for_key(db, business_key)
    if not dims and not snapshots and not conflicts:
        raise HTTPException(status_code=404, detail=MSG_RETRACTION_NOT_FOUND)

    existing = db.execute(
        select(RetractionBatch).where(RetractionBatch.business_key == business_key)
    ).scalar_one_or_none()

    if existing is not None and existing.status == RetractionStatus.CONFIRMED.value:
        # Already in force: return the same row, never create a second batch.
        return {**batch_payload(db, existing), "idempotent": True, "already_confirmed": True}

    impact = _impact(db, business_key)
    if existing is None:
        existing = RetractionBatch(
            business_key=business_key,
            status=RetractionStatus.PENDING.value,
            impact=impact,
            requested_by=actor_email,
            baseline_run_id=impact.get("pre_retraction_run_id"),
            notes=(notes or "")[:255],
        )
        db.add(existing)
    else:
        # pending / failed -> refresh manifest in place; no new row.
        existing.impact = impact
        existing.status = RetractionStatus.PENDING.value
        existing.requested_by = actor_email
        existing.notes = (notes or existing.notes or "")[:255]
        existing.baseline_run_id = impact.get("pre_retraction_run_id")
        existing.error_message = ""
    db.commit()
    db.refresh(existing)
    log_event("RETRACTION_BATCH_PENDING", batch_id=existing.id, business_key=business_key, actor=actor_email)
    return {**batch_payload(db, existing), "idempotent": False, "already_confirmed": False}


def confirm_batch(db: Session, batch_id: int, *, actor_email: str) -> dict:
    batch = get_batch(db, batch_id)
    guard = confirmation_guard(batch.status, retracted_keys(db), batch.business_key)
    if guard == "already_confirmed":
        # Idempotent: same retraction re-run adds no batch / backup rows.
        return {**batch_payload(db, batch), "idempotent": True, "already_confirmed": True}

    batch.attempt_count = int(batch.attempt_count or 0) + 1
    db.commit()

    try:
        _capture_backups(db, batch, batch.business_key)
        counts = _apply_redaction(db, batch, batch.business_key)
        _purge_backup_payloads(db, batch)

        batch.status = RetractionStatus.CONFIRMED.value
        batch.confirmed_by = actor_email
        batch.confirmed_at = datetime.now()
        batch.applied_run_id = _latest_run_id(db)
        batch.error_message = ""
        batch.impact = {**(batch.impact or {}), "applied": counts}
        db.commit()
    except Exception as exc:  # pragma: no cover - exercised through the failure test
        db.rollback()
        restored = _restore_from_backups(db, batch)
        restored_batch = db.get(RetractionBatch, batch.id)
        restored_batch.status = RetractionStatus.FAILED.value
        restored_batch.error_message = f"{type(exc).__name__}: {exc}"[:500]
        restored_batch.restored_at = datetime.now()
        restored_batch.impact = {**(restored_batch.impact or {}), "restored": restored, "error": restored_batch.error_message}
        db.commit()
        log_event("RETRACTION_FAILED_RESTORED", batch_id=batch.id, business_key=batch.business_key, error=str(exc))
        raise HTTPException(status_code=502, detail=restored_batch.error_message)

    log_event(
        "RETRACTION_CONFIRMED",
        batch_id=batch.id,
        business_key=batch.business_key,
        actor=actor_email,
        counts=counts,
    )
    return {**batch_payload(db, batch), "idempotent": False, "already_confirmed": False, "applied": counts}


def restore_batch(db: Session, batch_id: int, *, actor_email: str) -> dict:
    """Roll a failed retraction back to the last usable version (idempotent)."""
    batch = get_batch(db, batch_id)
    if not restore_snapshot(batch.status):
        raise HTTPException(status_code=409, detail=MSG_RETRACTION_NOT_RESTORABLE)
    restored = _restore_from_backups(db, batch)
    batch.status = RetractionStatus.FAILED.value
    batch.restored_at = batch.restored_at or datetime.now()
    batch.impact = {**(batch.impact or {}), "restored": restored}
    db.commit()
    log_event("RETRACTION_RESTORED", batch_id=batch.id, business_key=batch.business_key, actor=actor_email)
    return {**batch_payload(db, batch), "restored": restored}


# --------------------------------------------------------------------------- #
# guards reused by the build pipeline and read paths
# --------------------------------------------------------------------------- #
def retracted_keys(db: Session) -> set[str]:
    return privacy.confirmed_retraction_keys(db)


def apply_build_guards(db: Session, snapshots: list) -> list:
    """Mark build snapshots of retired customers so no personal value survives.

    A late (or replayed) snapshot for a confirmed-retracted customer keeps its
    anonymous chain but cannot contribute name / mobile / org back to it.
    """
    keys = retracted_keys(db)
    if not keys:
        return snapshots
    guarded = []
    for snapshot in snapshots:
        if late_snapshot_hidden(snapshot.business_key, keys):
            snapshot = type(snapshot)(
                business_key=snapshot.business_key,
                source_code=snapshot.source_code,
                snapshot_date=snapshot.snapshot_date,
                attributes=privacy.mask_attributes(snapshot.attributes),
                ingested_at=snapshot.ingested_at,
                trust=snapshot.trust,
                is_retracted=True,
            )
        guarded.append(snapshot)
    return guarded
