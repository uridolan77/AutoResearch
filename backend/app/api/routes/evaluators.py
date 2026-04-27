from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.api.schemas import (
    CreateEvaluatorRequest,
    CreateEvaluatorResponse,
    EvaluatorResponse,
)
from app.core.db import get_db
from app.models import Evaluator, Session
from app.models.enums import EvaluatorType, MetricDirection, NetworkMode

router = APIRouter(prefix="/evaluators", tags=["evaluators"])


def _validate_evaluator_payload(payload: CreateEvaluatorRequest) -> dict:
    name = payload.name.strip()
    type_raw = payload.type
    config = payload.config or {}
    metric_name = payload.metric_name.strip()
    direction_raw = payload.direction
    timeout_s = int(payload.timeout_s)
    baseline_required = bool(payload.baseline_required)
    network_mode_raw = payload.network_mode
    network_allow = payload.network_allow
    secret_refs = payload.secret_refs

    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    try:
        ev_type = EvaluatorType(type_raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail="invalid evaluator type") from e
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="config must be an object")
    if not metric_name:
        raise HTTPException(status_code=422, detail="metric_name is required")
    try:
        direction = MetricDirection(direction_raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail="invalid direction") from e
    try:
        network_mode = NetworkMode(network_mode_raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail="invalid network_mode") from e
    if network_mode not in (NetworkMode.none, NetworkMode.bridge):
        raise HTTPException(status_code=422, detail="network_mode must be none or bridge in Phase 1")

    # Type-specific config validation.
    if ev_type == EvaluatorType.command:
        if not config.get("image") or not config.get("command"):
            raise HTTPException(status_code=422, detail="command evaluator requires config.image and config.command")
        if not (config.get("metric_regex") or config.get("metric_path")):
            raise HTTPException(status_code=422, detail="command evaluator requires config.metric_regex or config.metric_path")
    elif ev_type == EvaluatorType.llm_judge:
        if not config.get("target_file") or not config.get("rubric_path"):
            raise HTTPException(status_code=422, detail="llm_judge evaluator requires config.target_file and config.rubric_path")

    return {
        "name": name,
        "type": ev_type,
        "config": config,
        "metric_name": metric_name,
        "direction": direction,
        "timeout_s": timeout_s,
        "baseline_required": baseline_required,
        "network_mode": network_mode,
        "network_allow": network_allow,
        "secret_refs": secret_refs,
    }


@router.get("")
def list_evaluators(db: DbSession = Depends(get_db)) -> list[EvaluatorResponse]:
    rows = db.query(Evaluator).order_by(Evaluator.name).all()
    return [
        EvaluatorResponse(
            id=r.id,
            name=r.name,
            type=r.type.value,
            config=r.config,
            metric_name=r.metric_name,
            direction=r.direction.value,
            timeout_s=r.timeout_s,
            baseline_required=r.baseline_required,
            network_mode=r.network_mode.value,
            network_allow=r.network_allow,
            secret_refs=r.secret_refs,
        )
        for r in rows
    ]


@router.post("", response_model=CreateEvaluatorResponse, status_code=status.HTTP_201_CREATED)
def create_evaluator(
    payload: CreateEvaluatorRequest,
    db: DbSession = Depends(get_db),
) -> CreateEvaluatorResponse:
    data = _validate_evaluator_payload(payload)
    row = Evaluator(**data)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="evaluator name already exists") from e
    db.refresh(row)
    return CreateEvaluatorResponse(id=row.id)


@router.get("/{evaluator_id}")
def get_evaluator(evaluator_id: str, db: DbSession = Depends(get_db)) -> EvaluatorResponse:
    row = db.get(Evaluator, evaluator_id)
    if row is None:
        raise HTTPException(status_code=404, detail="evaluator not found")
    return EvaluatorResponse(
        id=row.id,
        name=row.name,
        type=row.type.value,
        config=row.config,
        metric_name=row.metric_name,
        direction=row.direction.value,
        timeout_s=row.timeout_s,
        baseline_required=row.baseline_required,
        network_mode=row.network_mode.value,
        network_allow=row.network_allow,
        secret_refs=row.secret_refs,
    )


@router.delete("/{evaluator_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluator(evaluator_id: str, db: DbSession = Depends(get_db)) -> None:
    row = db.get(Evaluator, evaluator_id)
    if row is None:
        raise HTTPException(status_code=404, detail="evaluator not found")
    used = db.query(Session.id).filter(Session.evaluator_id == evaluator_id).first()
    if used is not None:
        raise HTTPException(status_code=409, detail="evaluator is in use by a session")
    db.delete(row)
    db.commit()
    return None

