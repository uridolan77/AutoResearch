import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { queryKeys } from '../api/queryKeys'
import { listSessions } from '../api/service'
import { LoadingBlock } from '../components/LoadingBlock'
import { StatusBadge } from '../components/StatusBadge'

export function SessionsPage() {
  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions.all,
    queryFn: listSessions,
    refetchInterval: 5_000,
  })

  if (sessionsQuery.isLoading) {
    return <LoadingBlock label="Loading sessions…" />
  }

  return (
    <section className="card stack-lg">
      <div>
        <p className="eyebrow">Sessions</p>
        <h2>Current runs and paused queues</h2>
      </div>

      <div className="table-like">
        {(sessionsQuery.data ?? []).map((session) => (
          <Link key={session.id} to={`/sessions/${session.id}`} className="row-link">
            <div>
              <strong>{session.name}</strong>
              <p className="muted">{session.id}</p>
            </div>
            <StatusBadge value={session.status} />
            <span>{session.tokens_used.toLocaleString()} tokens</span>
            <span>{session.created_at ? new Date(session.created_at).toLocaleString() : 'unknown'}</span>
          </Link>
        ))}
      </div>
    </section>
  )
}