from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.schemas import EstimateRequest, EstimateResponse
from app.agent.estimate import estimate_iteration_tokens

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/estimate", response_model=EstimateResponse, status_code=status.HTTP_200_OK)
def estimate(payload: EstimateRequest) -> EstimateResponse:
    program_md = payload.program_md
    folder_path = payload.folder_path.strip()
    target_file = payload.target_file.strip()
    if not folder_path:
        raise HTTPException(status_code=422, detail="folder_path is required")
    if not target_file:
        raise HTTPException(status_code=422, detail="target_file is required")

    max_files_per_diff = int(payload.max_files_per_diff)
    token_cap_iter = int(payload.token_cap_iter)

    result = estimate_iteration_tokens(
        program_md=str(program_md),
        folder_path=folder_path,
        target_file=target_file,
        max_files_per_diff=max_files_per_diff,
        token_cap_iter=token_cap_iter,
    )
    return EstimateResponse(**result)

