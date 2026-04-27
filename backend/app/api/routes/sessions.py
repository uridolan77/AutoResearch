from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session as DbSession

from app.api.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    ExperimentSummaryResponse,
    PatchProgramRequest,
    PatchProgramResponse,
    SessionActionResponse,
    SessionDetailResponse,
    SessionSummaryResponse,
)
from app.core.config import get_settings
from app.core.db import get_db
from app.git_service import GitError, GitService
from app.models import Experiment, Folder, Session
from app.models.enums import ExperimentStatus
from app.models.enums import ReviewMode, SessionStatus
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/sessions", tags=["sessions"])
ws_router = APIRouter(prefix="/ws/sessions", tags=["ws"])


def _ws_event_for_experiment(exp: Experiment | None) -> tuple[str, dict[str, Any]] | None:
    if exp is None:
        return None

    if exp.status in (ExperimentStatus.pending, ExperimentStatus.running, ExperimentStatus.deciding):
        return ("experiment.running", {"id": exp.id, "iteration": exp.iteration})
    if exp.status == ExperimentStatus.duplicate:
        return ("experiment.duplicate", {"id": exp.id, "matched_hash": exp.diff_hash})
    if exp.status == ExperimentStatus.scored:
        return (
            "experiment.scored",
            {
                "id": exp.id,
                "score_before": exp.score_before,
                "score_after": exp.score_after,
                "delta": exp.score_delta,
            },
        )
    if exp.status == ExperimentStatus.awaiting_review:
        return (
            "experiment.awaiting_review",
            {
                "id": exp.id,
                "delta": exp.score_delta,
                "score_before": exp.score_before,
                "score_after": exp.score_after,
            },
        )
    if exp.status == ExperimentStatus.kept:
        return ("experiment.kept", {"id": exp.id, "commit_sha": exp.experiment_commit})
    if exp.status == ExperimentStatus.reverted:
        return (
            "experiment.reverted",
            {
                "id": exp.id,
                "decision": exp.decision.value if exp.decision else None,
                "reason": exp.rejection_comment,
            },
        )
    if exp.status == ExperimentStatus.failed:
        return ("experiment.failed", {"id": exp.id, "reason": exp.rejection_comment})
    return None


@ws_router.websocket("/{session_id}")
async def session_events(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()

    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        if session is None:
            await websocket.send_json({"type": "error", "payload": {"detail": "session not found"}})
            await websocket.close(code=1008)
            return

        latest = (
            db.query(Experiment)
            .filter(Experiment.session_id == session_id)
            .order_by(Experiment.iteration.desc())
            .first()
        )

        await websocket.send_json({"type": "session.status", "payload": {"id": session.id, "status": session.status.value}})
        initial_event = _ws_event_for_experiment(latest)
        if initial_event is not None:
            event_type, payload = initial_event
            await websocket.send_json({"type": event_type, "payload": payload})

        last_session_status = session.status
        last_token_warning_sent = False  # tracks whether we've already emitted the 80% warning
        last_experiment_signature = (
            latest.id if latest else None,
            latest.status if latest else None,
            latest.decision if latest else None,
            latest.score_delta if latest else None,
            latest.experiment_commit if latest else None,
            latest.rejection_comment if latest else None,
        )

        while True:
            await asyncio.sleep(2)
            db.expire_all()

            session = db.get(Session, session_id)
            if session is None:
                await websocket.send_json({"type": "session.stopped", "payload": {"reason": "session deleted"}})
                await websocket.close(code=1000)
                return

            if session.status != last_session_status:
                await websocket.send_json({"type": "session.status", "payload": {"id": session.id, "status": session.status.value}})
                if session.status == SessionStatus.paused:
                    await websocket.send_json({"type": "session.paused", "payload": {"id": session.id}})
                if session.status in (SessionStatus.draining, SessionStatus.stopped, SessionStatus.complete):
                    await websocket.send_json({"type": "session.stopped", "payload": {"reason": session.status.value}})
                last_session_status = session.status

            # Token budget warning at 80% of session cap (one-shot).
            if (
                not last_token_warning_sent
                and session.token_cap_session > 0
                and (session.tokens_used or 0) >= session.token_cap_session * 0.8
            ):
                await websocket.send_json(
                    {
                        "type": "session.token_warning",
                        "payload": {
                            "id": session.id,
                            "tokens_used": session.tokens_used,
                            "token_cap_session": session.token_cap_session,
                        },
                    }
                )
                last_token_warning_sent = True

            latest = (
                db.query(Experiment)
                .filter(Experiment.session_id == session_id)
                .order_by(Experiment.iteration.desc())
                .first()
            )
            signature = (
                latest.id if latest else None,
                latest.status if latest else None,
                latest.decision if latest else None,
                latest.score_delta if latest else None,
                latest.experiment_commit if latest else None,
                latest.rejection_comment if latest else None,
            )
            if signature != last_experiment_signature:
                event = _ws_event_for_experiment(latest)
                if event is not None:
                    event_type, payload = event
                    await websocket.send_json({"type": event_type, "payload": payload})
                last_experiment_signature = signature
    except WebSocketDisconnect:
        return
    finally:
        db.close()


def _require_folder_path(db: DbSession, payload: CreateSessionRequest) -> str:
    folder_id = payload.folder_id
    folder_path = payload.folder_path
    if folder_id:
        row = db.get(Folder, str(folder_id))
        if row is None:
            raise HTTPException(status_code=404, detail="folder not found")
        return row.folder_path
    if folder_path:
        return str(folder_path)
    raise HTTPException(status_code=422, detail="folder_id or folder_path is required")

@router.post(
    "",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: CreateSessionRequest,
    db: DbSession = Depends(get_db),
) -> CreateSessionResponse:
    name = (payload.name or f"session-{uuid.uuid4().hex[:6]}").strip()
    folder_path = _require_folder_path(db, payload)
    target_file = (payload.target_file or "").strip()
    program_md = payload.program_md or ""
    evaluator_id = (payload.evaluator_id or "").strip()
    if not target_file:
        raise HTTPException(status_code=422, detail="target_file is required")
    if not evaluator_id:
        raise HTTPException(status_code=422, detail="evaluator_id is required")

    review_mode_raw = payload.review_mode
    try:
        review_mode = ReviewMode(review_mode_raw)
    except Exception as e:
        raise HTTPException(status_code=422, detail="invalid review_mode") from e

    s = Session(
        name=name,
        folder_path=folder_path,
        target_file=target_file,
        program_md=str(program_md),
        evaluator_id=evaluator_id,
        wall_clock_budget_s=int(payload.wall_clock_budget_s),
        token_cap_session=int(payload.token_cap_session),
        token_cap_iter=int(payload.token_cap_iter),
        max_files_per_diff=int(payload.max_files_per_diff),
        review_mode=review_mode,
        review_timeout_hours=int(payload.review_timeout_hours),
        worktree_prune_window=int(payload.worktree_prune_window),
        validation_retry_max=int(payload.validation_retry_max),
        status=SessionStatus.idle,
        tokens_used=0,
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    # Create session branch + base worktree.
    settings = get_settings()
    gitsvc = GitService(worktree_root=settings.worktree_root)
    repo_path = Path(s.folder_path)
    try:
        gitsvc.ensure_repo(repo_path)
        branch, _ = gitsvc.create_session_branch(repo_path, s.id)
    except GitError as e:
        db.delete(s)
        db.commit()
        raise HTTPException(status_code=400, detail=f"git error: {e}") from e

    s.session_branch = branch
    db.commit()

    return CreateSessionResponse(id=s.id)


@router.get("", response_model=list[SessionSummaryResponse])
def list_sessions(db: DbSession = Depends(get_db)) -> list[SessionSummaryResponse]:
    rows = db.query(Session).order_by(Session.created_at.desc()).all()
    return [
        SessionSummaryResponse(
            id=r.id,
            name=r.name,
            status=r.status.value,
            tokens_used=r.tokens_used,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(
    session_id: str,
    db: DbSession = Depends(get_db),
) -> SessionDetailResponse:
    s = db.get(Session, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionDetailResponse(
        id=s.id,
        name=s.name,
        folder_path=s.folder_path,
        target_file=s.target_file,
        program_md=s.program_md,
        evaluator_id=s.evaluator_id,
        wall_clock_budget_s=s.wall_clock_budget_s,
        token_cap_session=s.token_cap_session,
        token_cap_iter=s.token_cap_iter,
        max_files_per_diff=s.max_files_per_diff,
        review_mode=s.review_mode.value,
        review_timeout_hours=s.review_timeout_hours,
        worktree_prune_window=s.worktree_prune_window,
        validation_retry_max=s.validation_retry_max,
        status=s.status.value,
        tokens_used=s.tokens_used,
        session_branch=s.session_branch,
        created_at=s.created_at.isoformat() if s.created_at else None,
    )


@router.get("/{session_id}/experiments", response_model=list[ExperimentSummaryResponse])
def list_session_experiments(
    session_id: str,
    status: str | None = None,
    kept: bool | None = None,
    delta_min: float | None = None,
    delta_max: float | None = None,
    limit: int = 100,
    offset: int = 0,
    db: DbSession = Depends(get_db),
) -> list[ExperimentSummaryResponse]:
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    query = db.query(Experiment).filter(Experiment.session_id == session_id)

    if status is not None:
        try:
            query = query.filter(Experiment.status == ExperimentStatus(status))
        except ValueError as e:
            raise HTTPException(status_code=422, detail="invalid experiment status") from e
    if kept is not None:
        query = query.filter(Experiment.kept == kept)
    if delta_min is not None:
        query = query.filter(Experiment.score_delta.is_not(None))
        query = query.filter(Experiment.score_delta >= delta_min)
    if delta_max is not None:
        query = query.filter(Experiment.score_delta.is_not(None))
        query = query.filter(Experiment.score_delta <= delta_max)

    rows = (
        query.order_by(Experiment.iteration.desc())
        .offset(offset)
        .limit(max(1, min(limit, 500)))
        .all()
    )

    return [
        ExperimentSummaryResponse(
            id=row.id,
            session_id=row.session_id,
            iteration=row.iteration,
            status=row.status.value,
            score_before=row.score_before,
            score_after=row.score_after,
            score_delta=row.score_delta,
            tokens_used=row.tokens_used,
            decision=row.decision.value if row.decision else None,
            kept=row.kept,
            worktree_pruned=row.worktree_pruned,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]


@router.post(
    "/{session_id}/start",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_session(
    session_id: str,
    db: DbSession = Depends(get_db),
) -> SessionActionResponse:
    s = db.get(Session, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    if s.status == SessionStatus.idle:
        s.status = SessionStatus.running
        db.commit()
    celery_app.send_task("autoresearch.loop", args=[session_id])
    return SessionActionResponse(session_id=session_id, status=s.status.value)


@router.post(
    "/{session_id}/pause",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def pause_session(
    session_id: str,
    db: DbSession = Depends(get_db),
) -> SessionActionResponse:
    s = db.get(Session, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    s.status = SessionStatus.paused
    db.commit()
    return SessionActionResponse(session_id=session_id, status=s.status.value)


@router.post(
    "/{session_id}/resume",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_session(
    session_id: str,
    db: DbSession = Depends(get_db),
) -> SessionActionResponse:
    s = db.get(Session, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    s.status = SessionStatus.running
    db.commit()
    celery_app.send_task("autoresearch.loop", args=[session_id])
    return SessionActionResponse(session_id=session_id, status=s.status.value)


@router.post(
    "/{session_id}/stop",
    response_model=SessionActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def stop_session(
    session_id: str,
    db: DbSession = Depends(get_db),
) -> SessionActionResponse:
    s = db.get(Session, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    s.status = SessionStatus.stopped
    db.commit()
    return SessionActionResponse(session_id=session_id, status=s.status.value)


@router.patch("/{session_id}/program", response_model=PatchProgramResponse)
def patch_program(
    session_id: str,
    payload: PatchProgramRequest,
    db: DbSession = Depends(get_db),
) -> PatchProgramResponse:
    s = db.get(Session, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    s.program_md = payload.program_md
    db.commit()
    return PatchProgramResponse(session_id=session_id, program_md=s.program_md)

