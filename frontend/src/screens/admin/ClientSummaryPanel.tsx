import { useEffect, useState } from 'react'
import { fetchClientSummary, requestClientSummary, type ClientSummary } from '../../adminApi'
import { ApiError } from '../../api'

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

// The client's ≤500-word summary (read-only). "Summarize client" updates it
// from the previous version plus what arrived since; "Rebuild from scratch"
// re-reads her whole history. Every version is kept on the server.
export function ClientSummaryPanel({
  adminKey,
  userId,
  onUnauthorized,
}: {
  adminKey: string
  userId: string
  onUnauthorized: () => void
}) {
  const [summary, setSummary] = useState<ClientSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState<'update' | 'rebuild' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function handleError(err: unknown, fallback: string) {
    if (err instanceof ApiError && err.status === 401) onUnauthorized()
    else setError(err instanceof Error ? err.message : fallback)
  }

  useEffect(() => {
    let cancelled = false
    fetchClientSummary(adminKey, userId)
      .then((result) => !cancelled && setSummary(result.summary))
      .catch((err) => !cancelled && handleError(err, 'Could not load the client summary.'))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminKey, userId])

  async function run(rebuild: boolean) {
    if (rebuild && !window.confirm('Rebuild the summary from her whole history? The current version is kept.')) return
    setRunning(rebuild ? 'rebuild' : 'update')
    setError(null)
    setNotice(null)
    try {
      const result = await requestClientSummary(adminKey, userId, rebuild)
      setSummary(result.summary)
      if (result.nothing_new) setNotice(`Nothing new since ${formatWhen(result.summary.covers_until)}.`)
    } catch (err) {
      handleError(err, 'The summary could not be made. Try again.')
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="card admin__section client-summary">
      <div className="coach-ai__head">
        <div className="monitor__label">Client summary</div>
        <button className="btn-secondary" disabled={running !== null || loading} onClick={() => void run(false)}>
          {running === 'update' ? 'Summarizing… (up to a minute)' : 'Summarize client'}
        </button>
      </div>
      {loading && <p className="admin__muted">Loading…</p>}
      {!loading && !summary && !running && <p className="admin__muted">No summary yet.</p>}
      {summary && (
        <>
          <p className="admin__muted">
            Version {summary.version}
            {summary.rebuilt ? ' (rebuilt)' : ''} · includes data up to {formatWhen(summary.covers_until)}
            {summary.word_count ? ` · ${summary.word_count} words` : ''}
          </p>
          <pre className="client-summary__text">{summary.text}</pre>
        </>
      )}
      {notice && <p className="admin__muted">{notice}</p>}
      {error && <div className="admin__hint admin__hint--error">{error}</div>}
      {summary && (
        <button
          className="client-summary__rebuild"
          disabled={running !== null}
          onClick={() => void run(true)}
        >
          {running === 'rebuild' ? 'Rebuilding…' : 'Rebuild from scratch'}
        </button>
      )}
    </div>
  )
}
