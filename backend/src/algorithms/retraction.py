"""Retraction batch helpers — pure functions, no database access.

A retraction batch is created for one customer business key. Creating it only
produces a *pending* batch together with the impact manifest (what would be
hidden once confirmed). Confirmation is the only step that redacts data.
"""
from __future__ import annotations

from src.constants.retraction_status import RetractionStatus

PERSONAL_ATTRIBUTE_KEYS = ("full_name", "mobile", "org_code")
REDACTED_VALUE = "***"


def build_impact_manifest(
    *,
    business_key: str,
    chain_versions: int,
    chain_keys: set[str],
    snapshot_rows: int,
    snapshot_sources: list[str],
    conflict_rows: int,
    conflict_attribute_keys: list[str],
    pre_retraction_run_id: int | None,
    secret_field_occurrences: dict[str, int],
) -> dict:
    """Deterministic manifest shown to the operator before anything is hidden."""
    return {
        "business_key": business_key,
        "personal_fields": list(PERSONAL_ATTRIBUTE_KEYS),
        "targets": {
            "dim_versions": int(chain_versions),
            "dim_current_rows": int(len(chain_keys)),
            "snapshot_rows": int(snapshot_rows),
            "snapshot_sources": sorted(set(snapshot_sources)),
            "conflict_items": int(conflict_rows),
            "conflict_attribute_keys": sorted(set(conflict_attribute_keys)),
        },
        "will_hide": {
            "current_dimension": True,
            "as_of_time_travel": True,
            "csv_export": True,
            "history_drawer": True,
            "conflict_candidates": True,
            "raw_snapshots": True,
        },
        "preserve": {
            "anonymous_business_key": business_key,
            "chain_counters": int(chain_versions),
            "audit_counters": "不在撤回范围，保持不变",
        },
        "field_occurrences": {key: int(secret_field_occurrences.get(key, 0)) for key in PERSONAL_ATTRIBUTE_KEYS},
        "pre_retraction_run_id": pre_retraction_run_id,
        "will_retract": True,
    }


def confirmation_guard(batch_status: str, confirmed_keys: set[str], business_key: str) -> str | None:
    """Return a status code when a confirmation must not redo the redaction.

    ``idempotent`` / ``already_confirmed`` both mean: nothing to write.
    """
    if business_key in confirmed_keys:
        return "already_confirmed"
    if batch_status == RetractionStatus.CONFIRMED.value:
        return "already_confirmed"
    return None


def late_snapshot_hidden(business_key: str, confirmed_keys: set[str]) -> bool:
    """A late (or replayed) snapshot must never resurrect a retired customer."""
    return business_key in confirmed_keys


def restore_snapshot(batch_status: str) -> bool:
    """Only a failed confirmation may be rolled back to the previous version."""
    return batch_status == RetractionStatus.FAILED.value


def count_secret_occurrences(attributes: list[dict]) -> dict[str, int]:
    """Count how many rows still carry a non-empty personal value."""
    counts = {key: 0 for key in PERSONAL_ATTRIBUTE_KEYS}
    for payload in attributes:
        for key in PERSONAL_ATTRIBUTE_KEYS:
            value = (payload or {}).get(key)
            if value not in (None, "", "***"):
                counts[key] += 1
    return counts
