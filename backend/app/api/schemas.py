"""Pydantic request/response models for the API surface."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    name: str | None = None
    folder_id: str | None = None
    folder_path: str | None = None
    target_file: str | None = None
    program_md: str | None = ""
    evaluator_id: str | None = None
    wall_clock_budget_s: int = 600
    token_cap_session: int = 1_000_000
    token_cap_iter: int = 100_000
    max_files_per_diff: int = 1
    review_mode: str = "always"
    review_timeout_hours: int = 48
    worktree_prune_window: int = 10
    validation_retry_max: int = 3
    max_iterations: int = 0


class CreateSessionResponse(BaseModel):
    id: str


class SessionSummaryResponse(BaseModel):
    id: str
    name: str
    status: str
    tokens_used: int
    created_at: str | None


class SessionDetailResponse(BaseModel):
    id: str
    name: str
    folder_path: str
    target_file: str
    program_md: str
    evaluator_id: str
    wall_clock_budget_s: int
    token_cap_session: int
    token_cap_iter: int
    max_files_per_diff: int
    review_mode: str
    review_timeout_hours: int
    worktree_prune_window: int
    validation_retry_max: int
    max_iterations: int
    status: str
    tokens_used: int
    session_branch: str | None
    created_at: str | None


class SessionActionResponse(BaseModel):
    session_id: str
    status: str


class PatchProgramRequest(BaseModel):
    program_md: str


class PatchProgramResponse(BaseModel):
    session_id: str
    program_md: str


class FolderIngestRequest(BaseModel):
    path_or_url: str


class FolderIngestResponse(BaseModel):
    folder_id: str
    folder_path: str
    is_git_clone: bool
    original: str


class FolderTargetsResponse(BaseModel):
    folder_id: str
    targets: list[str]


class EvaluatorResponse(BaseModel):
    id: str
    name: str
    type: str
    config: dict[str, Any]
    metric_name: str
    direction: str
    timeout_s: int
    baseline_required: bool
    network_mode: str
    network_allow: list[str] | None
    secret_refs: list[str] | None


class CreateEvaluatorRequest(BaseModel):
    name: str
    type: str
    config: dict[str, Any]
    metric_name: str
    direction: str
    timeout_s: int = 600
    baseline_required: bool = True
    network_mode: str = "none"
    network_allow: list[str] | None = None
    secret_refs: list[str] | None = None


class CreateEvaluatorResponse(BaseModel):
    id: str


class EstimateRequest(BaseModel):
    program_md: str = ""
    folder_path: str
    target_file: str
    max_files_per_diff: int = 1
    token_cap_iter: int = 100_000


class EstimateResponse(BaseModel):
    estimated_input_tokens: int
    estimated_max_output_tokens: int
    estimated_total_tokens: int
    token_cap_iter: int | None = None
    within_cap: bool | None = None


class DiffViewResponse(BaseModel):
    file_path: str | None
    old_text: str
    new_text: str


class RunSummaryResponse(BaseModel):
    id: str
    worker_id: str | None
    start_at: str | None
    end_at: str | None
    stdout_path: str | None
    stderr_path: str | None
    metric_payload: dict | None
    exit_code: int | None


class RejectionHistoryEntryResponse(BaseModel):
    id: str
    iteration: int
    rejection_comment: str
    decision: str | None
    created_at: str | None


class ExperimentSummaryResponse(BaseModel):
    id: str
    session_id: str
    iteration: int
    status: str
    score_before: float | None
    score_after: float | None
    score_delta: float | None
    tokens_used: int
    decision: str | None
    kept: bool
    worktree_pruned: bool
    created_at: str | None


class ExperimentDetailResponse(BaseModel):
    id: str
    session_id: str
    iteration: int
    parent_commit: str | None
    experiment_commit: str | None
    branch_ref: str | None
    status: str
    diff_text: str | None
    diff_view: DiffViewResponse | None
    diff_hash: str | None
    validation_attempts: int
    score_before: float | None
    score_after: float | None
    score_delta: float | None
    tokens_used: int
    decision: str | None
    rejection_comment: str | None
    kept: bool
    worktree_pruned: bool
    created_at: str | None
    runs: list[RunSummaryResponse]
    rejection_history: list[RejectionHistoryEntryResponse]


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=500)


class ReviewResponse(BaseModel):
    experiment_id: str
    status: str
    decision: str
    queued_decide: bool


class SkipResponse(BaseModel):
    experiment_id: str
    status: str
    decision: str
    queued_decide: bool
