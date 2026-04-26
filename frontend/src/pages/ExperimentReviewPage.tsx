import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { queryKeys } from '../api/queryKeys'
import { getExperiment, reviewExperiment, skipExperiment } from '../api/service'
import { LoadingBlock } from '../components/LoadingBlock'
import { StatusBadge } from '../components/StatusBadge'

export function ExperimentReviewPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const params = useParams<{ sessionId: string; experimentId: string }>()
  const sessionId = params.sessionId ?? ''
  const experimentId = params.experimentId ?? ''
  const [comment, setComment] = useState('')
  const commentRef = useRef<HTMLTextAreaElement | null>(null)

  const experimentQuery = useQuery({
    queryKey: queryKeys.experiments.detail(experimentId),
    queryFn: () => getExperiment(experimentId),
    enabled: Boolean(experimentId),
    refetchInterval: 3_000,
  })

  const reviewMutation = useMutation({
    mutationFn: (payload: { decision: 'approve' | 'reject'; comment?: string }) =>
      reviewExperiment(experimentId, payload.decision, payload.comment),
    onSuccess: (data) => {
      toast.success(`Decision queued: ${data.decision}`)
      void queryClient.invalidateQueries({ queryKey: queryKeys.experiments.detail(experimentId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.experiments(sessionId) })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.error('This experiment already has a queued decision.')
      }
    },
  })

  const skipMutation = useMutation({
    mutationFn: () => skipExperiment(experimentId),
    onSuccess: () => {
      toast.success('Experiment marked as skipped.')
      void queryClient.invalidateQueries({ queryKey: queryKeys.experiments.detail(experimentId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions.experiments(sessionId) })
    },
  })

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) {
        if (event.key.toLowerCase() !== 'e') {
          return
        }
      }

      if (event.key.toLowerCase() === 'a') {
        event.preventDefault()
        reviewMutation.mutate({ decision: 'approve' })
      }
      if (event.key.toLowerCase() === 'r') {
        event.preventDefault()
        reviewMutation.mutate({ decision: 'reject', comment })
      }
      if (event.key.toLowerCase() === 'e') {
        event.preventDefault()
        commentRef.current?.focus()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [comment, reviewMutation])

  if (experimentQuery.isLoading) {
    return <LoadingBlock label="Loading experiment…" />
  }

  const experiment = experimentQuery.data
  if (!experiment) {
    return <LoadingBlock label="Experiment not found." />
  }

  return (
    <div className="page-grid detail-grid">
      <section className="card stack-lg">
        <div className="split-row">
          <div>
            <p className="eyebrow">Review</p>
            <h2>Iteration {experiment.iteration}</h2>
            <p className="muted">{experiment.id}</p>
          </div>
          <StatusBadge value={experiment.status} />
        </div>

        <div className="meta-grid">
          <div>
            <span className="meta-label">Score delta</span>
            <strong>{experiment.score_delta ?? 'n/a'}</strong>
          </div>
          <div>
            <span className="meta-label">Decision</span>
            <strong>{experiment.decision ?? 'pending'}</strong>
          </div>
          <div>
            <span className="meta-label">Validation attempts</span>
            <strong>{experiment.validation_attempts}</strong>
          </div>
        </div>

        <div className="diff-panel">
          <pre>{experiment.diff_text ?? 'No diff recorded.'}</pre>
        </div>
      </section>

      <section className="card stack-lg">
        <div>
          <p className="eyebrow">Decision rail</p>
          <h2>Approve or reject the change</h2>
        </div>

        <label className="field">
          <span>Rejection comment</span>
          <textarea ref={commentRef} value={comment} onChange={(event) => setComment(event.target.value.slice(0, 500))} rows={8} />
          <small className="muted">{comment.length}/500 characters · shortcuts: A approve, R reject, E focus comment</small>
        </label>

        <div className="button-row wrap">
          <button type="button" className="button button-primary" onClick={() => reviewMutation.mutate({ decision: 'approve' })} disabled={reviewMutation.isPending || skipMutation.isPending}>
            Approve
          </button>
          <button type="button" className="button button-danger" onClick={() => reviewMutation.mutate({ decision: 'reject', comment })} disabled={reviewMutation.isPending || skipMutation.isPending}>
            Reject
          </button>
          <button type="button" className="button button-secondary" onClick={() => skipMutation.mutate()} disabled={reviewMutation.isPending || skipMutation.isPending}>
            Skip
          </button>
          <button type="button" className="button button-ghost" onClick={() => navigate(`/sessions/${sessionId}`)}>
            Back to session
          </button>
        </div>

        <div className="stack-md">
          <div>
            <h3>Run metadata</h3>
            {experiment.runs.length === 0 ? (
              <p className="muted">No run records captured yet.</p>
            ) : (
              experiment.runs.map((run) => (
                <div key={run.id} className="nested-card">
                  <strong>{run.worker_id ?? 'unknown worker'}</strong>
                  <p className="muted">stdout: {run.stdout_path ?? 'n/a'} · stderr: {run.stderr_path ?? 'n/a'}</p>
                </div>
              ))
            )}
          </div>

          <div>
            <h3>Recent rejection history</h3>
            {experiment.rejection_history.length === 0 ? (
              <p className="muted">No rejection comments captured yet.</p>
            ) : (
              experiment.rejection_history.map((entry) => (
                <div key={entry.id} className="nested-card">
                  <strong>Iteration {entry.iteration}</strong>
                  <p>{entry.rejection_comment}</p>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  )
}