"""Retraction flow tests — pure algorithm tests plus DB-backed service tests.

DB tests run only when ``SCD_TEST_DB`` is set, e.g.:

    SCD_TEST_DB='postgresql+psycopg2://user:pwd@127.0.0.1:55432/db' \
        python -m pytest tests/test_retraction.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

SCD_TEST_DB = os.environ.get("SCD_TEST_DB", "")
if SCD_TEST_DB:
    # Point the shared engine at the isolated test database *before* importing
    # src.config.database (settings are read at import time).
    from sqlalchemy.engine import make_url

    url = make_url(SCD_TEST_DB)
    os.environ["DB_HOST"] = url.host or "127.0.0.1"
    os.environ["DB_PORT"] = str(url.port or 5432)
    os.environ["DB_NAME"] = url.database or "scdchain_test"
    os.environ["DB_USER"] = url.username or "postgres"
    os.environ["DB_PASSWORD"] = url.password or ""
else:
    os.environ.setdefault("DB_HOST", "127.0.0.1")
    os.environ.setdefault("DB_PORT", "55432")

from src.algorithms.retraction import (  # noqa: E402
    build_impact_manifest,
    confirmation_guard,
    late_snapshot_hidden,
    restore_snapshot,
)
from src.algorithms.scd2 import AttributeRule, Snapshot, build_zipper  # noqa: E402


# --------------------------------------------------------------------------- #
# pure algorithm tests (no database)
# --------------------------------------------------------------------------- #
RULES = [
    AttributeRule(key="customer_level", source_priority=("core_policy",), normalization="direct"),
    AttributeRule(key="full_name", source_priority=("core_policy",), normalization="name_homophone"),
    AttributeRule(key="mobile", source_priority=("core_policy",), normalization="phone_digits"),
    AttributeRule(key="org_code", source_priority=("core_policy",), normalization="org_code_map"),
    AttributeRule(key="city", source_priority=("core_policy",), normalization="direct"),
]


def _snap(day: date, name: str, level: str = "金卡", retracted: bool = False, city: str = "北京") -> Snapshot:
    return Snapshot(
        business_key="CUST-0001",
        source_code="core_policy",
        snapshot_date=day,
        attributes={"full_name": name, "mobile": "13900000001", "org_code": "BJ01",
                    "customer_level": level, "city": city},
        ingested_at=datetime(day.year, day.month, day.day, 6, 0),
        is_retracted=retracted,
    )


def test_manifest_lists_personal_fields_and_preserves_key():
    manifest = build_impact_manifest(
        business_key="CUST-0001",
        chain_versions=3,
        chain_keys={"CUST-0001"},
        snapshot_rows=5,
        snapshot_sources=["core_policy"],
        conflict_rows=1,
        conflict_attribute_keys=["mobile"],
        pre_retraction_run_id=7,
        secret_field_occurrences={"full_name": 8, "mobile": 8, "org_code": 8},
    )
    assert manifest["personal_fields"] == ["full_name", "mobile", "org_code"]
    assert manifest["targets"]["dim_versions"] == 3
    assert manifest["preserve"]["anonymous_business_key"] == "CUST-0001"
    assert manifest["will_retract"] is True


def test_guard_helpers():
    assert confirmation_guard("pending", set(), "CUST-1") is None
    assert confirmation_guard("confirmed", {"CUST-1"}, "CUST-1") == "already_confirmed"
    assert late_snapshot_hidden("CUST-1", {"CUST-1"}) is True
    assert late_snapshot_hidden("CUST-2", {"CUST-1"}) is False
    assert restore_snapshot("failed") is True
    assert restore_snapshot("confirmed") is False


def test_retracted_snapshot_never_opens_personal_change_chain():
    days = [date(2026, 11, 1) + timedelta(days=i) for i in range(4)]
    rows = [
        _snap(days[0], "张三"),
        _snap(days[1], "李四"),                                    # 注销前：姓名变化 -> 正常开链
        _snap(days[2], "王五", retracted=True),                    # 注销后：迟到快照只有姓名变化
        _snap(days[3], "赵六", retracted=True, city="上海"),        # 注销后：非个人字段仍可开链
    ]
    outcome = build_zipper(rows, RULES)
    # 第 2 天（注销前）的姓名变化照常开链；第 3 天的注销后迟到快照不得开链；
    # 第 4 天仅个人字段之外的变化（city）仍照常留链，且注销段落的个人字段只能是掩码。
    assert len(outcome.versions) == 3
    assert [version.attributes["full_name"] for version in outcome.versions] == ["张三", "李四", "***"]
    assert outcome.versions[-1].change_fields == ["city"]
    assert outcome.versions[-1].attributes["full_name"] == "***"
    assert outcome.invariants["all_passed"] is True


# --------------------------------------------------------------------------- #
# DB-backed service tests
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_session():
    if not SCD_TEST_DB:
        pytest.skip("SCD_TEST_DB not set; DB-backed retraction tests skipped")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.config.database import Base
    from src.config import models_registry  # noqa: F401

    engine = create_engine(SCD_TEST_DB, future=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield session, engine
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def seeded(db_session):
    db, _engine = db_session
    from scripts.seed_demo import run_seed
    from src.config.database import init_db

    init_db()
    run_seed()
    yield db


def _personal_present(attributes: dict) -> bool:
    return any(attributes.get(key) not in (None, "", "***") for key in ("full_name", "mobile", "org_code"))


def test_retraction_confirm_hides_every_layer_and_is_idempotent(seeded):
    from sqlalchemy import func, select

    from src.models.customer_snapshot import CustomerSnapshot
    from src.models.dim_customer import DimCustomer
    from src.models.retraction_batch import RetractionBatch
    from src.models.retraction_backup import RetractionBackup
    from src.services import dim_service, retraction_service
    from src.utils.pagination import pagination

    db = seeded
    key = "CUST-0060"

    preview = retraction_service.preview_impact(db, key)
    assert preview["impact"]["personal_fields"] == ["full_name", "mobile", "org_code"]

    batch = retraction_service.create_batch(db, key, actor_email="admin@scdchain.io")
    assert batch["status"] == "pending"
    # nothing is hidden while pending
    row = [i for i in dim_service.current_dims(db, "", "", pagination(1, 300))["items"] if i["business_key"] == key][0]
    assert row["full_name"] != "***"

    confirmed = retraction_service.confirm_batch(db, batch["id"], actor_email="admin@scdchain.io")
    assert confirmed["status"] == "confirmed"

    # current dimension, as-of and history / export all hide the three fields
    row = [i for i in dim_service.current_dims(db, "", "", pagination(1, 300))["items"] if i["business_key"] == key][0]
    assert row["full_name"] == row["mobile"] == row["org_code"] == "***"
    history = dim_service.history(db, key)
    assert all(v["full_name"] == "***" for v in history["versions"])
    assert all(_personal_present(v["attributes"]) is False for v in history["versions"])
    assert history["retracted"] is True
    as_of = dim_service.as_of_query(db, date(2026, 11, 3), "", "", pagination(1, 300))
    assert all(i["full_name"] == "***" for i in as_of["items"] if i["business_key"] == key)

    from src.controllers.dim_controller import export_as_of

    csv = export_as_of(db, "2026-11-05").body.decode("utf-8")
    line = [l for l in csv.splitlines() if key in l][0]
    assert "***" in line

    # raw store is redacted, the anonymous key and the counters survive
    assert db.execute(
        select(func.count(CustomerSnapshot.id)).where(CustomerSnapshot.business_key == key)
    ).scalar() == 5
    assert db.execute(
        select(func.count(DimCustomer.id)).where(DimCustomer.business_key == key)
    ).scalar() == 4
    assert all(row.business_key == key for row in db.execute(
        select(DimCustomer).where(DimCustomer.business_key == key)).scalars())

    # idempotency: re-create / re-confirm adds no batch and no backup row
    again = retraction_service.create_batch(db, key, actor_email="admin@scdchain.io")
    assert again["id"] == batch["id"] and again["idempotent"] is True
    again = retraction_service.confirm_batch(db, batch["id"], actor_email="admin@scdchain.io")
    assert again["idempotent"] is True
    assert db.execute(select(func.count(RetractionBatch.id))).scalar() == 1
    assert db.execute(
        select(func.count(RetractionBackup.id)).where(RetractionBackup.retraction_id == batch["id"])
    ).scalar() == confirmed["backup_rows"] == 9


def test_confirmation_failure_restores_last_usable_version(seeded, monkeypatch):
    from src.services import dim_service, retraction_service
    from src.utils.pagination import pagination

    db = seeded
    key = "CUST-0060"
    before = [i for i in dim_service.current_dims(db, "", "", pagination(1, 300))["items"] if i["business_key"] == key][0]
    batch = retraction_service.create_batch(db, key, actor_email="modeler@scdchain.io")

    original_apply = retraction_service._apply_redaction

    def explode(*args, **kwargs):
        # redact nothing, then die half-way through the confirmation transaction
        raise RuntimeError("simulated redaction crash")

    monkeypatch.setattr(retraction_service, "_apply_redaction", explode)
    with pytest.raises(Exception):
        retraction_service.confirm_batch(db, batch["id"], actor_email="modeler@scdchain.io")

    failed = retraction_service.get_batch(db, batch["id"])
    assert failed.status == "failed"
    assert "simulated redaction crash" in failed.error_message

    # restore puts the last usable version back: personal data is visible again,
    # the anonymous key and the chain counters were never touched
    restored = retraction_service.restore_batch(db, batch["id"], actor_email="modeler@scdchain.io")
    assert restored["status"] == "failed" and restored["restored"]["dim_versions"] == 4
    after = [i for i in dim_service.current_dims(db, "", "", pagination(1, 300))["items"] if i["business_key"] == key][0]
    assert after["full_name"] == before["full_name"] != "***"
    assert after["mobile"] == before["mobile"]
    assert dim_service.history(db, key)["retracted"] is False

    # restore is itself idempotent; a retry of the confirmation then succeeds
    retraction_service.restore_batch(db, batch["id"], actor_email="modeler@scdchain.io")
    monkeypatch.setattr(retraction_service, "_apply_redaction", original_apply)
    ok = retraction_service.confirm_batch(db, batch["id"], actor_email="modeler@scdchain.io")
    assert ok["status"] == "confirmed"
    assert ok["attempt_count"] == 2


def test_late_snapshot_cannot_resurrect_retired_customer(seeded):
    from datetime import date as _date, datetime as _datetime

    from sqlalchemy import select

    from src.models.customer_snapshot import CustomerSnapshot
    from src.models.dim_customer import DimCustomer
    from src.models.source_system import SourceSystem
    from src.services import build_service, dim_service, retraction_service

    db = seeded
    key = "CUST-0060"
    batch = retraction_service.create_batch(db, key, actor_email="admin@scdchain.io")
    retraction_service.confirm_batch(db, batch["id"], actor_email="admin@scdchain.io")

    # a late snapshot dated before the running max arrives after the retraction
    source = db.execute(select(SourceSystem).where(SourceSystem.code == "core_policy")).scalar_one()
    db.add(
        CustomerSnapshot(
            source_id=source.id,
            source_code="core_policy",
            business_key=key,
            snapshot_date=_date(2026, 11, 2),
            attributes={"full_name": "罗欣悦", "mobile": "13900002183", "org_code": "CD04",
                        "customer_level": "金卡", "city": "成都", "channel": "银保"},
            row_hash="late-row",
            ingested_at=_datetime(2026, 11, 6, 23, 0),
            is_late=True,
            batch_tag="late-replay",
        )
    )
    db.commit()

    run = build_service.create_run(
        db, actor_email="modeler@scdchain.io", label="late-after-retraction", dispatch=False
    )
    result = build_service.execute_run(db, run.id)
    assert result["ok"] is True
    assert result["invariants"]["all_passed"] is True

    chain = db.execute(
        select(DimCustomer).where(DimCustomer.build_run_id == run.id, DimCustomer.business_key == key)
    ).scalars().all()
    assert chain and all(row.attributes["full_name"] == "***" for row in chain)
    assert all(row.attributes["mobile"] == "***" for row in chain)
    # anonymous key is still present, one current row per key
    assert all(row.business_key == key for row in chain)
    assert sum(1 for row in chain if row.is_current) == 1
    assert dim_service.history(db, key)["versions"][-1]["full_name"] == "***"


def test_conflict_resolution_is_blocked_for_retired_customer(seeded):
    from fastapi import HTTPException
    from sqlalchemy import select

    from src.models.conflict_item import ConflictItem
    from src.services import conflict_service, retraction_service

    db = seeded
    row = db.execute(
        select(ConflictItem).where(ConflictItem.status == "open").order_by(ConflictItem.id).limit(1)
    ).scalar_one()
    key = row.business_key
    batch = retraction_service.create_batch(db, key, actor_email="admin@scdchain.io")
    retraction_service.confirm_batch(db, batch["id"], actor_email="admin@scdchain.io")

    # masked candidates are no longer real values: the adjudication is refused
    with pytest.raises(HTTPException) as excinfo:
        conflict_service.resolve(
            db, row.id, strategy="candidate", value="***", note="", actor_email="modeler@scdchain.io"
        )
    assert excinfo.value.status_code == 409


def test_build_compare_reads_are_redacted_after_retraction(seeded):
    from sqlalchemy import select

    from src.models.build_run import BuildRun
    from src.services import build_service, retraction_service

    db = seeded
    batch = retraction_service.create_batch(db, "CUST-0060", actor_email="admin@scdchain.io")
    retraction_service.confirm_batch(db, batch["id"], actor_email="admin@scdchain.io")

    runs = db.execute(select(BuildRun).where(BuildRun.status == "succeeded").order_by(BuildRun.id)).scalars().all()
    detail = build_service.run_detail(db, runs[0].id)
    sample = [row for row in detail["chain_samples"] if row["business_key"] == "CUST-0060"]
    for row in sample:
        assert row["attributes"]["full_name"] == "***"

    compared = build_service.compare_runs(db, runs[0].id, runs[-1].id)
    for section in ("new_chain_samples", "removed_chain_samples"):
        for row in compared[section]:
            if row["business_key"] == "CUST-0060":
                assert row["attributes"]["full_name"] == "***"
    for row in compared["current_change_samples"]:
        if row["business_key"] == "CUST-0060":
            assert row["left"]["full_name"] == "***"
            assert row["right"]["full_name"] == "***"
