export type ReviewMode = 'always' | 'improvements_only' | 'auto_approve'
export type SessionStatus = 'idle' | 'running' | 'paused' | 'draining' | 'stopped' | 'complete'
export type ExperimentStatus =
  | 'pending'
  | 'running'
  | 'scored'
  | 'awaiting_review'
  | 'kept'
  | 'reverted'
  | 'failed'
  | 'duplicate'

export interface FolderIngestResponse {
  folder_id: string
  folder_path: string
  is_git_clone: boolean
  original: string
}

export interface TargetsResponse {
  folder_id: string
  targets: string[]
}

export interface Evaluator {
  id: string
  name: string
  type: string
  config: Record<string, unknown>
  metric_name: string
  direction: string
  timeout_s: number
  baseline_required: boolean
  network_mode: string
  network_allow: string[] | null
  secret_refs: string[] | null
}

export interface SessionSummary {
  id: string
  name: string
  status: SessionStatus
  tokens_used: number
  created_at: string | null
}

export interface SessionDetail extends SessionSummary {
  folder_path: string
  target_file: string
  program_md: string
  evaluator_id: string
  wall_clock_budget_s: number
  token_cap_session: number
  token_cap_iter: number
  max_files_per_diff: number
  review_mode: ReviewMode
  review_timeout_hours: number
  worktree_prune_window: number
  validation_retry_max: number
  session_branch: string | null
}

export interface SessionActionResponse {
  session_id: string
  status: SessionStatus
}

export interface CreateSessionRequest {
  name?: string
  folder_id?: string
  folder_path?: string
  target_file: string
  program_md?: string
  evaluator_id: string
  wall_clock_budget_s?: number
  token_cap_session?: number
  token_cap_iter?: number
  max_files_per_diff?: number
  review_mode?: ReviewMode
  review_timeout_hours?: number
  worktree_prune_window?: number
  validation_retry_max?: number
}

export interface CreateSessionResponse {
  id: string
}

export interface EstimateResponse {
  estimated_input_tokens: number
  estimated_max_output_tokens: number
  estimated_total_tokens: number
  token_cap_iter?: number
  within_cap?: boolean
}

export interface ExperimentSummary {
  id: string
  session_id: string
  iteration: number
  status: ExperimentStatus
  score_before: number | null
  score_after: number | null
  score_delta: number | null
  tokens_used: number
  decision: string | null
  kept: boolean
  worktree_pruned: boolean
  created_at: string | null
}

export interface RunSummary {
  id: string
  worker_id: string | null
  start_at: string | null
  end_at: string | null
  stdout_path: string | null
  stderr_path: string | null
  metric_payload: Record<string, unknown> | null
  exit_code: number | null
}

export interface RejectionHistoryEntry {
  id: string
  iteration: number
  rejection_comment: string
  decision: string | null
  created_at: string | null
}

export interface ExperimentDetail extends ExperimentSummary {
  parent_commit: string | null
  experiment_commit: string | null
  branch_ref: string | null
  diff_text: string | null
  diff_view: {
    file_path: string | null
    old_text: string
    new_text: string
  } | null
  diff_hash: string | null
  validation_attempts: number
  rejection_comment: string | null
  runs: RunSummary[]
  rejection_history: RejectionHistoryEntry[]
}

export interface ReviewResponse {
  experiment_id: string
  status: ExperimentStatus
  decision: string
  queued_decide: boolean
}

export interface SessionEvent {
  type: string
  payload: Record<string, unknown>
}