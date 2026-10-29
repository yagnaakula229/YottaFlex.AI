import { useEffect, useState } from 'react'
import './App.css'

const DEFAULT_API = 'http://localhost:8000'

function isDemoSummary(payload) {
  return (
    payload !== null &&
    typeof payload === 'object' &&
    payload.mode === 'synthetic-demo' &&
    payload.synthetic === true &&
    Array.isArray(payload.recovery_candidates) &&
    Array.isArray(payload.message_events) &&
    Array.isArray(payload.orders) &&
    payload.backend_health !== null &&
    typeof payload.backend_health === 'object' &&
    typeof payload.backend_health.ready === 'string' &&
    payload.attribution !== null &&
    typeof payload.attribution === 'object' &&
    Number.isInteger(payload.attribution.credited_orders) &&
    Number.isInteger(payload.attribution.uncredited_orders) &&
    Number.isInteger(payload.attribution.attribution_window_days)
  )
}

function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    let active = true
    const apiBase = import.meta.env.VITE_API_URL || DEFAULT_API

    fetch(`${apiBase}/api/demo/summary`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Request failed with status ${response.status}`)
        }
        return response.json()
      })
      .then((payload) => {
        if (!isDemoSummary(payload)) {
          throw new Error('Backend response did not match the demo summary schema')
        }
        if (active) {
          setData(payload)
          setError('')
        }
      })
      .catch((fetchError) => {
        if (active) {
          setData(null)
          setError(fetchError.message)
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [retryCount])

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">YottaFlex.AI</p>
          <h1>Consent-aware recovery dashboard</h1>
        </div>
        <span className="demo-badge">Synthetic demo</span>
      </header>

      {loading && <div className="status-card" role="status">Loading dashboard data…</div>}
      {error && (
        <div className="status-card error" role="alert">
          <span>Backend unavailable: {error}</span>
          <button type="button" onClick={() => setRetryCount((count) => count + 1)}>
            Retry
          </button>
        </div>
      )}

      {data && (
        <>
          <section className="metrics-grid">
            <article className="metric-card">
              <span>Recovery candidates</span>
              <strong>{data.recovery_candidates.length}</strong>
            </article>
            <article className="metric-card">
              <span>Attributed orders</span>
              <strong>{data.attribution.credited_orders}</strong>
            </article>
            <article className="metric-card">
              <span>Message events</span>
              <strong>{data.message_events.length}</strong>
            </article>
            <article className="metric-card">
              <span>Backend health</span>
              <strong>{data.backend_health.ready}</strong>
            </article>
          </section>

          <section className="panel-grid">
            <article className="panel">
              <h2>Recovery candidates</h2>
              <ul className="list">
                {data.recovery_candidates.length === 0 ? (
                  <li className="empty-state">No recovery candidates.</li>
                ) : (
                  data.recovery_candidates.map((candidate) => (
                    <li key={candidate.customer_id}>
                      <div>
                        <strong>{candidate.customer_id}</strong>
                        <small>{candidate.cart_id}</small>
                      </div>
                      <span>{candidate.channel}</span>
                      <em>{candidate.score}</em>
                    </li>
                  ))
                )}
              </ul>
            </article>

            <article className="panel">
              <h2>Message event history</h2>
              <ul className="list">
                {data.message_events.length === 0 ? (
                  <li className="empty-state">No message events.</li>
                ) : (
                  data.message_events.map((event) => (
                    <li key={event.event_id}>
                      <div>
                        <strong>{event.event_type}</strong>
                        <small>{event.event_id}</small>
                      </div>
                      <span>{event.customer_id}</span>
                      <em>{event.status}</em>
                    </li>
                  ))
                )}
              </ul>
            </article>
          </section>

          <section className="panel">
            <h2>Order attribution</h2>
            <div className="attribution-row">
              <div>
                <span>Credited</span>
                <strong>{data.attribution.credited_orders}</strong>
              </div>
              <div>
                <span>Uncredited</span>
                <strong>{data.attribution.uncredited_orders}</strong>
              </div>
              <div>
                <span>Window</span>
                <strong>{data.attribution.attribution_window_days} days</strong>
              </div>
            </div>
          </section>
        </>
      )}
    </main>
  )
}

export default App
