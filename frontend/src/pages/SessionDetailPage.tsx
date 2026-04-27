import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import type { SessionEvent } from '../api/types'
import { queryKeys } from '../api/queryKeys'
import { getSession, listSessionExperiments, patchProgram, sessionAction } from '../api/service'
import { LoadingBlock } from '../components/LoadingBlock'
import { StatusBadge } from '../components/StatusBadge'
import { TokenBar } from '../components/TokenBar'
import { useSessionWebSocket } from '../hooks/useSessionWebSocket'

export function SessionDetailPage() {
  const params = useParams<{ sessionId: string }>()
  const sessionId = params.sessionId ?? ''
  const queryClient = useQueryClient()
  const [draftProgram, setDraftProgram] = useState('')

  const { connected: wsConnected } = useSessionWebSocket(sessionId, (event: SessionEvent) => {
    if (!event?.type) return
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.detail(sessionId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.experiments(sessionId) })
    if (event.type === 'session.token_warning') {
      toast.warning('Session token usage crossed warning threshold.')
    }
  })

  const sessionQuery = useQuery({
    queryKey: queryKeys.sessions.detail(sessionId),
    queryFn: () => getSession(sessionId),
    enabled: Boolean(sessionId),
    refetchInterval: wsConnected ? 10_000 : 3_000,
  })

  const experimentsQuery = useQuery({
    queryKey: queryKeys.sessions.experiments(sessionId),
    queryFn: () => listSessionExperiments(sessionId),
    enabled: Boolean(sessionId),
    refetchInterval: wsConnected ? 10_000 : 3_000,
  })

  const actionMutation = useMutation({
    mutationFn: (action: 'start' | 'pause' | 'resume' | 'stop') => sessionAction(sessionId, action),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.detail(sessionId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.experiments(sessionId) })
    },
  })

  const patchMutation = useMutation({
    mutationFn: (programMd: string) => patchProgram(sessionId, programMd),
    onSuccess: (data) => {
      setDraftProgram(data.program_md)
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.detail(sessionId) })
      toast.success('program.md updated for the next iteration.')
    },
  })

  const currentExperiment = useMemo(() => (experimentsQuery.data ?? [])[0] ?? null, [experimentsQuery.data])
  useEffect(() => {
    if (sessionQuery.data) {
      setDraftProgram(sessionQuery.data.program_md)
    }
  }, [sessionQuery.data])

  if (sessionQuery.isLoading) {
    return <LoadingBlock label="Loading session…" />
  }

  const session = sessionQuery.data
  if (!session) {
    return <LoadingBlock label="Session not found." />
  }

  return (
    <div className="page-grid detail-grid">
      <section className="card stack-lg">
        <div className="split-row">
          <div>
            <p className="eyebrow">Session detail</p>
            <h2>{session.name}</h2>
            <p className="muted">{session.target_file} · evaluator {session.evaluator_id}</p>
          </div>
          <StatusBadge value={session.status} />
        </div>

        <TokenBar used={session.tokens_used} cap={session.token_cap_session} />

        <div className="button-row wrap">
          <button type="button" className="button button-primary" onClick={() => actionMutation.mutate('start')} disabled={actionMutation.isPending}>Start</button>
          <button type="button" className="button button-secondary" onClick={() => actionMutation.mutate('pause')} disabled={actionMutation.isPending}>Pause</button>
          <button type="button" className="button button-secondary" onClick={() => actionMutation.mutate('resume')} disabled={actionMutation.isPending}>Resume</button>
          <button type="button" className="button button-danger" onClick={() => actionMutation.mutate('stop')} disabled={actionMutation.isPending}>Stop</button>
        </div>

        <div className="meta-grid">
          <div>
            <span className="meta-label">Folder</span>
            <strong>{session.folder_path}</strong>
          </div>
          <div>
            <span className="meta-label">Review mode</span>
            <strong>{session.review_mode}</strong>
          </div>
          <div>
            <span className="meta-label">Current experiment</span>
            <strong>{currentExperiment ? `#${currentExperiment.iteration}` : 'none yet'}</strong>
          </div>
          <div>
            <span className="meta-label">Live stream</span>
            <strong>{wsConnected ? 'connected' : 'polling fallback'}</strong>
          </div>
        </div>

        <label className="field">
          <span>program.md</span>
          <textarea value={draftProgram} onChange={(event) => setDraftProgram(event.target.value)} rows={12} />
        </label>
        <button type="button" className="button button-primary" onClick={() => patchMutation.mutate(draftProgram)} disabled={patchMutation.isPending}>
          {patchMutation.isPending ? 'Saving…' : 'Save program.md'}
        </button>
      </section>

      <section className="card stack-lg">
        <div>
          <p className="eyebrow">Experiments</p>
          <h2>Timeline feed</h2>
        </div>

        <div className="timeline-list">
          {(experimentsQuery.data ?? []).map((experiment) => (
            <Link key={experiment.id} to={`/sessions/${sessionId}/experiments/${experiment.id}`} className="timeline-item">
              <div>
                <strong>Iteration {experiment.iteration}</strong>
                <p className="muted">Δ {experiment.score_delta ?? 'n/a'} · {experiment.tokens_used.toLocaleString()} tokens</p>
              </div>
              <StatusBadge value={experiment.status} />
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}