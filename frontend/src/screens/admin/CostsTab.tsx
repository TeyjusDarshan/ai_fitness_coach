import { Fragment, useEffect, useState } from 'react'
import { fetchCosts, type CostSummary, type FeatureCost } from '../../adminApi'
import { ApiError } from '../../api'

const RANGES = [7, 30, 90] as const

const FEATURE_LABELS: Record<string, string> = {
  summary_questions: 'Workout summary + questions',
  feedback_extraction: 'Voice-note notes',
  reply_mapping: 'Reply mapping',
  coach_suggestions: 'AI Coach suggestions',
  plan_generation: 'Plan generation',
  profile_generation: 'Profile generation',
  voice_note_stt: 'Voice notes → text',
  reply_stt: 'Voice replies → text',
  summary_tts: 'Summary voice note',
  follow_up_tts: 'Follow-up voice note',
}

const PROVIDER_LABELS = { anthropic: 'Claude', sarvam: 'Sarvam' } as const

const rupees = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })

function inr(value: number | null | undefined): string {
  return value == null ? '—' : rupees.format(value)
}

function featureLabel(feature: string): string {
  const dryRun = feature.startsWith('dry_run_')
  const base = dryRun ? feature.slice('dry_run_'.length) : feature
  const label = FEATURE_LABELS[base] ?? base
  return dryRun ? `${label} (dry run)` : label
}

function formatWhen(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// Coach-only: what the AI features cost, per client, over a recent window —
// every Claude and Sarvam call recorded in ai_usage, in rupees (Claude
// converted at the server's USD_INR_RATE).
export function CostsTab({ adminKey, onUnauthorized }: { adminKey: string; onUnauthorized: () => void }) {
  const [days, setDays] = useState<number>(30)
  const [includeDryRuns, setIncludeDryRuns] = useState(false)
  const [data, setData] = useState<CostSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchCosts(adminKey, days, includeDryRuns)
      .then((result) => !cancelled && setData(result))
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) onUnauthorized()
        else setError(err instanceof Error ? err.message : 'Could not load the costs.')
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminKey, days, includeDryRuns, reload])

  return (
    <div className="costs">
      <div className="costs__controls">
        <div className="admin__segmented costs__range" role="tablist" aria-label="Period">
          {RANGES.map((range) => (
            <button
              key={range}
              type="button"
              role="tab"
              aria-selected={days === range}
              className={`admin__segment${days === range ? ' admin__segment--active' : ''}`}
              onClick={() => setDays(range)}
            >
              Last {range} days
            </button>
          ))}
        </div>
        <label className="costs__toggle">
          <input type="checkbox" checked={includeDryRuns} onChange={(e) => setIncludeDryRuns(e.target.checked)} />
          Include dry runs
        </label>
        <button type="button" className="btn-link" disabled={loading} onClick={() => setReload((n) => n + 1)}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {data && (
        <>
          <div className="costs__stats">
            <Stat label={`Total, last ${data.days} days`} value={inr(data.total_inr)} strong />
            <Stat label="Claude" value={inr(data.claude_inr)} />
            <Stat label="Sarvam (voice)" value={inr(data.sarvam_inr)} />
            <Stat label="Clients with spend" value={String(data.active_clients)} />
            <Stat label="Average per client" value={inr(data.per_client_inr)} />
          </div>

          <section className="card costs__section">
            <h2 className="costs__title">Per client</h2>
            {data.clients.length === 0 ? (
              <p className="admin__muted">No AI usage recorded in this period.</p>
            ) : (
              <div className="costs__scroll">
                <table className="costs__table">
                  <thead>
                    <tr>
                      <th>Client</th>
                      <th className="costs__num">Total</th>
                      <th className="costs__num">Claude</th>
                      <th className="costs__num">Sarvam</th>
                      <th className="costs__num">Workouts</th>
                      <th className="costs__num">Per workout</th>
                      <th>Last activity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.clients.map((client) => {
                      const expanded = open === client.user_id
                      return (
                        <Fragment key={client.user_id}>
                          <tr
                            className={`costs__row${expanded ? ' costs__row--open' : ''}`}
                            onClick={() => setOpen(expanded ? null : client.user_id)}
                          >
                            <td>
                              <button type="button" className="costs__client" aria-expanded={expanded}>
                                <span className="costs__caret" aria-hidden>
                                  {expanded ? '▾' : '▸'}
                                </span>
                                <span>
                                  <span className="costs__name">{client.name ?? client.user_id}</span>
                                  {client.name && <span className="costs__id">{client.user_id}</span>}
                                </span>
                              </button>
                            </td>
                            <td className="costs__num costs__total">{inr(client.total_inr)}</td>
                            <td className="costs__num">{inr(client.claude_inr)}</td>
                            <td className="costs__num">{inr(client.sarvam_inr)}</td>
                            <td className="costs__num">{client.workouts}</td>
                            <td className="costs__num">{inr(client.per_workout_inr)}</td>
                            <td>{formatWhen(client.last_at)}</td>
                          </tr>
                          {expanded && (
                            <tr className="costs__detail">
                              <td colSpan={7}>
                                <FeatureTable features={client.by_feature} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {data.by_feature.length > 0 && (
            <section className="card costs__section">
              <h2 className="costs__title">By feature</h2>
              <FeatureTable features={data.by_feature} />
            </section>
          )}

          <p className="admin__muted costs__note">
            Claude is converted at ₹{data.usd_inr_rate} per $. Sarvam prices exclude GST. Only calls made since cost
            tracking was added are counted.
          </p>
        </>
      )}
    </div>
  )
}

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`card costs__stat${strong ? ' costs__stat--strong' : ''}`}>
      <div className="costs__stat-value">{value}</div>
      <div className="costs__stat-label">{label}</div>
    </div>
  )
}

function FeatureTable({ features }: { features: FeatureCost[] }) {
  return (
    <div className="costs__scroll">
      <table className="costs__table costs__table--compact">
        <thead>
          <tr>
            <th>Feature</th>
            <th>Provider</th>
            <th className="costs__num">Calls</th>
            <th className="costs__num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {features.map((f) => (
            <tr key={`${f.provider}:${f.feature}`}>
              <td>{featureLabel(f.feature)}</td>
              <td>{PROVIDER_LABELS[f.provider] ?? f.provider}</td>
              <td className="costs__num">{f.calls}</td>
              <td className="costs__num">{inr(f.inr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
