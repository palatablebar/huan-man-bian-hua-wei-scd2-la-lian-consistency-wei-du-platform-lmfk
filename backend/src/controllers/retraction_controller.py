from fastapi import Request
from sqlalchemy.orm import Session

from src.schemas.retraction import RetractionCreateRequest
from src.services import audit_service, retraction_service


def _audit(db: Session, actor: dict, request: Request, action: str, resource_id: str, detail: dict) -> None:
    audit_service.record(
        db,
        actor_email=actor["email"],
        actor_role=actor["role"],
        action=action,
        resource_type="retraction_batch",
        resource_id=resource_id,
        detail=detail,
        ip=request.client.host if request.client else "",
        request_id=getattr(request.state, "request_id", ""),
    )


def list_batches(db: Session, status: str = "all", business_key: str = "") -> dict:
    return {
        "items": retraction_service.list_batches(db, status, business_key),
        "summary": retraction_service.summary(db),
    }


def preview(db: Session, business_key: str) -> dict:
    """Impact manifest preview without persisting a batch."""
    return retraction_service.preview_impact(db, business_key)


def create_batch(db: Session, payload: RetractionCreateRequest, actor: dict, request: Request) -> dict:
    result = retraction_service.create_batch(
        db, payload.business_key, actor_email=actor["email"], notes=payload.notes
    )
    _audit(
        db,
        actor,
        request,
        "retraction.batch.create",
        str(result["id"]),
        {
            "business_key": payload.business_key,
            "status": result["status"],
            "idempotent": result.get("idempotent", False),
            "impact": result.get("impact", {}),
        },
    )
    return result


def confirm_batch(db: Session, batch_id: int, actor: dict, request: Request) -> dict:
    result = retraction_service.confirm_batch(db, batch_id, actor_email=actor["email"])
    _audit(
        db,
        actor,
        request,
        "retraction.batch.confirm",
        str(batch_id),
        {
            "business_key": result["business_key"],
            "status": result["status"],
            "idempotent": result.get("idempotent", False),
            "applied": result.get("applied", {}),
        },
    )
    return result


def restore_batch(db: Session, batch_id: int, actor: dict, request: Request) -> dict:
    result = retraction_service.restore_batch(db, batch_id, actor_email=actor["email"])
    _audit(
        db,
        actor,
        request,
        "retraction.batch.restore",
        str(batch_id),
        {"business_key": result["business_key"], "restored": result.get("restored", {})},
    )
    return result
