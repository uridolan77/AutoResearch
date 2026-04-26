from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.agent.estimate import estimate_iteration_tokens

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/estimate", status_code=status.HTTP_200_OK)
def estimate(payload: dict) -> dict:
    program_md = payload.get("program_md") or ""
    folder_path = (payload.get("folder_path") or "").strip()
    target_file = (payload.get("target_file") or "").strip()
    if not folder_path:
        raise HTTPException(status_code=422, detail="folder_path is required")
    if not target_file:
        raise HTTPException(status_code=422, detail="target_file is required")

    max_files_per_diff = int(payload.get("max_files_per_diff") or 1)
    token_cap_iter = int(payload.get("token_cap_iter") or 100_000)

    return estimate_iteration_tokens(
        program_md=str(program_md),
        folder_path=folder_path,
        target_file=target_file,
        max_files_per_diff=max_files_per_diff,
        token_cap_iter=token_cap_iter,
    )

