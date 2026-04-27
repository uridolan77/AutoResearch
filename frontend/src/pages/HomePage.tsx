import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { ApiError } from '../api/client'
import { createSession, estimateSession, fetchEvaluators, fetchTargets, ingestFolder } from '../api/service'
import { queryKeys } from '../api/queryKeys'

export function HomePage() {
  const navigate = useNavigate()
  const [pathOrUrl, setPathOrUrl] = useState('')
  const [folderId, setFolderId] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [targetFile, setTargetFile] = useState('')
  const [programMd, setProgramMd] = useState('## Goal\nImprove the target file without broadening scope.\n')
  const [reviewMode, setReviewMode] = useState<'always' | 'improvements_only' | 'auto_approve'>('always')
  const [estimation, setEstimation] = useState<string>('')

  const evaluatorsQuery = useQuery({
    queryKey: queryKeys.evaluators.all,
    queryFn: fetchEvaluators,
  })

  const [selectedEvaluatorId, setSelectedEvaluatorId] = useState('')

  const targetsQuery = useQuery({
    queryKey: queryKeys.folders.targets(folderId),
    queryFn: () => fetchTargets(folderId),
    enabled: Boolean(folderId),
  })

  const ingestMutation = useMutation({
    mutationFn: () => ingestFolder(pathOrUrl),
    onSuccess: (data) => {
      setFolderId(data.folder_id)
      setFolderPath(data.folder_path)
      toast.success('Folder registered.')
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(error.message)
      }
    },
  })

  const estimateMutation = useMutation({
    mutationFn: () =>
      estimateSession({
        program_md: programMd,
        folder_path: folderPath,
        target_file: targetFile,
      }),
    onSuccess: (data) => {
      setEstimation(`${Number(data.estimated_total_tokens).toLocaleString()} estimated tokens / iteration`)
    },
  })

  const createMutation = useMutation({
    mutationFn: () =>
      createSession({
        folder_id: folderId,
        target_file: targetFile,
        program_md: programMd,
        evaluator_id: selectedEvaluatorId,
        review_mode: reviewMode,
      }),
    onSuccess: (data) => {
      toast.success('Session created.')
      navigate(`/sessions/${data.id}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        toast.error('Check the required fields and try again.')
      }
    },
  })

  const evaluatorOptions = evaluatorsQuery.data ?? []
  const targets = useMemo(() => targetsQuery.data?.targets ?? [], [targetsQuery.data])

  return (
    <div className="page-grid two-up">
      <section className="card stack-lg">
        <div>
          <p className="eyebrow">Ingest</p>
          <h2>Register a repo or local folder</h2>
          <p className="muted">Start from a local path or git clone URL. The backend will resolve it into a folder record and suggest editable targets.</p>
        </div>

        <label className="field">
          <span>Path or git URL</span>
          <input value={pathOrUrl} onChange={(event) => setPathOrUrl(event.target.value)} placeholder="C:\\dev\\AutoResearch\\_toy_repo or https://..." />
        </label>

        <div className="button-row">
          <button type="button" className="button button-primary" onClick={() => ingestMutation.mutate()} disabled={!pathOrUrl || ingestMutation.isPending}>
            {ingestMutation.isPending ? 'Registering…' : 'Register folder'}
          </button>
          {folderPath && <p className="inline-note">Resolved path: <strong>{folderPath}</strong></p>}
        </div>

        <label className="field">
          <span>Suggested target file</span>
          <select value={targetFile} onChange={(event) => setTargetFile(event.target.value)} disabled={!folderId || targetsQuery.isLoading}>
            <option value="">Select target</option>
            {targets.map((target) => (
              <option key={target} value={target}>{target}</option>
            ))}
          </select>
        </label>
      </section>

      <section className="card stack-lg">
        <div>
          <p className="eyebrow">Session</p>
          <h2>Create the first reviewable loop</h2>
          <p className="muted">This first frontend cut keeps the form narrow: choose the evaluator, review mode, and operator instructions.</p>
        </div>

        <label className="field">
          <span>Evaluator</span>
          <select value={selectedEvaluatorId} onChange={(event) => setSelectedEvaluatorId(event.target.value)}>
            <option value="">Select evaluator</option>
            {evaluatorOptions.map((evaluator) => (
              <option key={evaluator.id} value={evaluator.id}>{evaluator.name} · {evaluator.type}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Review mode</span>
          <select value={reviewMode} onChange={(event) => setReviewMode(event.target.value as typeof reviewMode)}>
            <option value="always">always</option>
            <option value="improvements_only">improvements_only</option>
            <option value="auto_approve">auto_approve</option>
          </select>
        </label>

        <label className="field">
          <span>Program.md</span>
          <textarea value={programMd} onChange={(event) => setProgramMd(event.target.value)} rows={10} />
        </label>

        <div className="button-row wrap">
          <button type="button" className="button button-secondary" onClick={() => estimateMutation.mutate()} disabled={!folderPath || !targetFile || estimateMutation.isPending}>
            {estimateMutation.isPending ? 'Estimating…' : 'Estimate cost'}
          </button>
          <button type="button" className="button button-primary" onClick={() => createMutation.mutate()} disabled={!folderId || !targetFile || !selectedEvaluatorId || createMutation.isPending}>
            {createMutation.isPending ? 'Creating…' : 'Create session'}
          </button>
        </div>
        {estimation && <p className="inline-note">{estimation}</p>}
      </section>
    </div>
  )
}