import { apiRequest } from './client'
import type {
  CreateSessionRequest,
  CreateSessionResponse,
  EstimateResponse,
  Evaluator,
  ExperimentDetail,
  ExperimentSummary,
  FolderIngestResponse,
  ReviewResponse,
  SessionActionResponse,
  SessionDetail,
  SessionSummary,
  TargetsResponse,
} from './types'

export function ingestFolder(pathOrUrl: string) {
  return apiRequest<FolderIngestResponse>('/folders/ingest', {
    method: 'POST',
    body: JSON.stringify({ path_or_url: pathOrUrl }),
  })
}

export function fetchTargets(folderId: string) {
  return apiRequest<TargetsResponse>(`/folders/${folderId}/targets`)
}

export function fetchEvaluators() {
  return apiRequest<Evaluator[]>('/evaluators')
}

export function estimateSession(payload: {
  program_md: string
  folder_path: string
  target_file: string
  max_files_per_diff?: number
  token_cap_iter?: number
}) {
  return apiRequest<EstimateResponse>('/sessions/estimate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function createSession(payload: CreateSessionRequest) {
  return apiRequest<CreateSessionResponse>('/sessions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listSessions() {
  return apiRequest<SessionSummary[]>('/sessions')
}

export function getSession(sessionId: string) {
  return apiRequest<SessionDetail>(`/sessions/${sessionId}`)
}

export function listSessionExperiments(sessionId: string) {
  return apiRequest<ExperimentSummary[]>(`/sessions/${sessionId}/experiments`)
}

export function patchProgram(sessionId: string, programMd: string) {
  return apiRequest<{ session_id: string; program_md: string }>(`/sessions/${sessionId}/program`, {
    method: 'PATCH',
    body: JSON.stringify({ program_md: programMd }),
  })
}

export function sessionAction(sessionId: string, action: 'start' | 'pause' | 'resume' | 'stop') {
  return apiRequest<SessionActionResponse>(`/sessions/${sessionId}/${action}`, {
    method: 'POST',
  })
}

export function getExperiment(experimentId: string) {
  return apiRequest<ExperimentDetail>(`/experiments/${experimentId}`)
}

export function reviewExperiment(experimentId: string, decision: 'approve' | 'reject', comment?: string) {
  return apiRequest<ReviewResponse>(`/experiments/${experimentId}/review`, {
    method: 'POST',
    body: JSON.stringify({ decision, comment }),
  })
}

export function skipExperiment(experimentId: string) {
  return apiRequest<ReviewResponse>(`/experiments/${experimentId}/skip`, {
    method: 'POST',
  })
}