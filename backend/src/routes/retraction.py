from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import Role
from src.controllers import retraction_controller
from src.middlewares.rbac import require_roles
from src.schemas.retraction import RetractionCreateRequest
from src.services import retraction_service

router = APIRouter(prefix="/retractions", tags=["retraction"])


@router.get("")
def list_batches(
    status: str = "all",
    business_key: str = "",
    db: Session = Depends(get_db),
    _: dict = Depends(require_roles(Role.ADMIN, Role.MODELER, Role.AUDITOR)),
) -> dict:
    return retraction_controller.list_batches(db, status, business_key)


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _: dict = Depends(require_roles(Role.ADMIN, Role.MODELER, Role.AUDITOR)),
) -> dict:
    return retraction_service.summary(db)


@router.get("/preview")
def preview(
    business_key: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_roles(Role.ADMIN, Role.MODELER)),
) -> dict:
    return retraction_controller.preview(db, business_key)


@router.post("", status_code=201)
def create_batch(
    payload: RetractionCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: dict = Depends(require_roles(Role.ADMIN, Role.MODELER)),
) -> dict:
    return retraction_controller.create_batch(db, payload, actor, request)


@router.post("/{batch_id}/confirm")
def confirm_batch(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: dict = Depends(require_roles(Role.ADMIN, Role.MODELER)),
) -> dict:
    return retraction_controller.confirm_batch(db, batch_id, actor, request)


@router.post("/{batch_id}/restore")
def restore_batch(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: dict = Depends(require_roles(Role.ADMIN, Role.MODELER)),
) -> dict:
    return retraction_controller.restore_batch(db, batch_id, actor, request)
