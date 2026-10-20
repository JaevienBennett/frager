import { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TOKEN_KEY = 'frager_token'
const REQUEST_TIMEOUT_MS = 60000
const NETWORK_ERROR =
  "Couldn't reach the server. It may be waking up — please try again in a moment."
const WAKING_UP = 'Waking up the server…'

async function fetchJson(url, options = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let res
  try {
    res = await fetch(url, { ...options, signal: controller.signal })
  } catch {
    throw new Error(NETWORK_ERROR)
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`
    try {
      const body = await res.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {}
    throw new Error(detail)
  }
  return res.json()
}

async function fetchJsonWithRetry(url, options = {}, attempts = 3) {
  let lastError
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await fetchJson(url, options)
    } catch (err) {
      lastError = err
      if (err.message !== NETWORK_ERROR || attempt === attempts - 1) throw err
      await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
    }
  }
  throw lastError
}

function parseStake(raw) {
  const trimmed = String(raw ?? '').trim()
  if (trimmed === '') return 0
  if (!/^\d+$/.test(trimmed)) {
    throw new Error('Stake must be a whole number of points (0 or more).')
  }
  return Math.min(Number(trimmed), 1000000)
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(() => !!localStorage.getItem(TOKEN_KEY))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [mode, setMode] = useState('login')
  const [error, setError] = useState('')

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
    setError('')
  }, [])

  const loadMe = useCallback(async (tok) => {
    try {
      const me = await fetchJsonWithRetry(`${API}/api/auth/me`, {
        headers: { Authorization: `Bearer ${tok}` },
      })
      setUser(me)
      setError('')
    } catch (err) {
      if (err.message === NETWORK_ERROR) {
        setError(err.message)
      } else {
        localStorage.removeItem(TOKEN_KEY)
        setToken(null)
        setUser(null)
        setError('Session expired, please log in again.')
      }
    } finally {
      setBooting(false)
    }
  }, [])

  useEffect(() => {
    if (token) loadMe(token)
    else setBooting(false)
  }, [token, loadMe])

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      const body =
        mode === 'signup' ? { email, nickname, password } : { email, password }
      const data = await fetchJson(`${API}/api/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      localStorage.setItem(TOKEN_KEY, data.access_token)
      setPassword('')
      setNickname('')
      setToken(data.access_token)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem', maxWidth: 420 }}>
      <h1>Frager</h1>

      {booting ? (
        <p>{WAKING_UP}</p>
      ) : user ? (
        <section>
          <p data-testid="user-status">Logged in as {user.nickname}</p>
          <button onClick={logout}>Log out</button>
          <Leagues token={token} userId={user.id} />
        </section>
      ) : (
        <form onSubmit={submit} style={{ display: 'grid', gap: 8 }}>
          <h2>{mode === 'login' ? 'Log in' : 'Sign up'}</h2>
          <input
            type="email"
            placeholder="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          {mode === 'signup' && (
            <input
              placeholder="nickname (2-24 chars)"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              required
              minLength={2}
              maxLength={24}
            />
          )}
          <input
            type="password"
            placeholder="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit">{mode === 'login' ? 'Log in' : 'Sign up'}</button>
          <button
            type="button"
            onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}
          >
            {mode === 'login' ? 'Need an account? Sign up' : 'Have an account? Log in'}
          </button>
        </form>
      )}

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
    </main>
  )
}

function Leagues({ token, userId }) {
  const [leagues, setLeagues] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [name, setName] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [newLeague, setNewLeague] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')

  const auth = { Authorization: `Bearer ${token}` }

  const loadLeagues = useCallback(async () => {
    try {
      const data = await fetchJsonWithRetry(`${API}/api/leagues`, { headers: auth })
      setLeagues(data)
    } catch (err) {
      setError(err.message)
    }
  }, [token])

  useEffect(() => {
    loadLeagues().finally(() => setLoaded(true))
  }, [loadLeagues])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      const league = await fetchJson(`${API}/api/leagues`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      setNewLeague(league)
      setName('')
      await loadLeagues()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleJoin(e) {
    e.preventDefault()
    setError('')
    try {
      await fetchJson(`${API}/api/leagues/join`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: joinCode }),
      })
      setJoinCode('')
      await loadLeagues()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section style={{ marginTop: '1.5rem' }}>
      <h2>Leagues</h2>

      <form onSubmit={handleCreate} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <input
          placeholder="league name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <button type="submit">Create league</button>
      </form>

      <form onSubmit={handleJoin} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <input
          placeholder="invite code"
          value={joinCode}
          onChange={(e) => setJoinCode(e.target.value)}
          required
        />
        <button type="submit">Join league</button>
      </form>

      {newLeague && (
        <p data-testid="new-league">
          Created <strong>{newLeague.name}</strong> — invite code:{' '}
          <code style={{ fontSize: '1.1em', fontWeight: 700 }}>{newLeague.invite_code}</code>
        </p>
      )}

      {!loaded ? (
        <p>{WAKING_UP}</p>
      ) : (
        <ul style={{ paddingLeft: '1.2rem' }}>
          {leagues.map((l) => (
            <li key={l.id} data-testid="league-item" style={{ marginBottom: 4 }}>
              <button
                onClick={() => setSelected(l)}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  font: 'inherit',
                  textDecoration: 'underline',
                  cursor: 'pointer',
                }}
              >
                {l.name}
              </button>{' '}
              — {l.member_count} member{l.member_count === 1 ? '' : 's'} · code{' '}
              <code>{l.invite_code}</code>
            </li>
          ))}
        </ul>
      )}

      {error && <p style={{ color: 'crimson' }}>{error}</p>}

      {selected && (
        <LeagueView
          token={token}
          userId={userId}
          league={selected}
          onBack={() => setSelected(null)}
        />
      )}
    </section>
  )
}

function LeagueView({ token, userId, league, onBack }) {
  const [predictions, setPredictions] = useState([])
  const [leaderboard, setLeaderboard] = useState([])
  const [details, setDetails] = useState({})
  const [expanded, setExpanded] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [question, setQuestion] = useState('')
  const [error, setError] = useState('')
  const [picks, setPicks] = useState({})
  const [saving, setSaving] = useState({})

  const auth = { Authorization: `Bearer ${token}` }

  const loadPredictions = useCallback(async () => {
    try {
      const data = await fetchJsonWithRetry(
        `${API}/api/leagues/${league.id}/predictions`,
        { headers: auth },
      )
      setPredictions(data)
    } catch (err) {
      setError(err.message)
    }
  }, [league.id, token])

  const loadLeaderboard = useCallback(async () => {
    try {
      const data = await fetchJsonWithRetry(
        `${API}/api/leagues/${league.id}/leaderboard`,
        { headers: auth },
      )
      setLeaderboard(data)
    } catch (err) {
      setError(err.message)
    }
  }, [league.id, token])

  const loadDetail = useCallback(
    async (predictionId) => {
      try {
        const data = await fetchJsonWithRetry(
          `${API}/api/predictions/${predictionId}`,
          { headers: auth },
        )
        setDetails((prev) => ({ ...prev, [predictionId]: data }))
      } catch (err) {
        setError(err.message)
      }
    },
    [token],
  )

  function toggleDetail(predictionId) {
    if (expanded === predictionId) {
      setExpanded(null)
      return
    }
    setExpanded(predictionId)
    if (!details[predictionId]) loadDetail(predictionId)
  }

  useEffect(() => {
    Promise.all([loadPredictions(), loadLeaderboard()]).finally(() =>
      setLoaded(true),
    )
  }, [loadPredictions, loadLeaderboard])

  function updatePickForm(predictionId, field, value) {
    setPicks((prev) => ({
      ...prev,
      [predictionId]: { side: 'yes', stake: '', ...prev[predictionId], [field]: value },
    }))
  }

  async function handlePost(e) {
    e.preventDefault()
    setError('')
    try {
      await fetchJson(`${API}/api/leagues/${league.id}/predictions`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      setQuestion('')
      await loadPredictions()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handlePick(e, predictionId) {
    e.preventDefault()
    setError('')
    const form = picks[predictionId] || { side: 'yes', stake: '' }
    let stake
    try {
      stake = parseStake(form.stake)
    } catch (err) {
      setError(err.message)
      return
    }
    setSaving((prev) => ({ ...prev, [predictionId]: true }))
    try {
      await fetchJson(`${API}/api/predictions/${predictionId}/pick`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ side: form.side, stake }),
      })
      setPicks((prev) => ({ ...prev, [predictionId]: { side: form.side, stake: '' } }))
      await Promise.all([loadPredictions(), loadDetail(predictionId)])
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving((prev) => ({ ...prev, [predictionId]: false }))
    }
  }

  async function handleResolve(predictionId, outcome) {
    setError('')
    try {
      await fetchJson(`${API}/api/predictions/${predictionId}/resolve`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome }),
      })
      await Promise.all([
        loadPredictions(),
        loadLeaderboard(),
        loadDetail(predictionId),
      ])
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section
      data-testid="league-view"
      style={{ marginTop: '1rem', borderTop: '1px solid #999', paddingTop: '0.5rem' }}
    >
      <button onClick={onBack}>← Back to leagues</button>
      <h3>{league.name}</h3>

      <form onSubmit={handlePost} style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          placeholder="Ask a yes/no question…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          required
          style={{ flex: 1 }}
        />
        <button type="submit">Post prediction</button>
      </form>

      {!loaded ? (
        <p>{WAKING_UP}</p>
      ) : (
        <>
          <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 12 }}>
            {predictions.map((p) => (
              <li
                key={p.id}
                data-testid="prediction-item"
                style={{ border: '1px solid #ccc', padding: 8 }}
              >
                <div>
                  <button
                    onClick={() => toggleDetail(p.id)}
                    data-testid="toggle-picks"
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: 0,
                      font: 'inherit',
                      fontWeight: 700,
                      textDecoration: 'underline',
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                  >
                    {p.question}
                  </button>{' '}
                  <em>({p.status})</em>
                </div>
                {p.status === 'resolved' && (
                  <div
                    data-testid="outcome-banner"
                    style={{
                      fontWeight: 700,
                      marginTop: 2,
                      color: p.resolved_outcome === 'yes' ? '#137333' : '#c5221f',
                    }}
                  >
                    Resolved: {String(p.resolved_outcome).toUpperCase()}
                  </div>
                )}
                <div data-testid="prediction-counts">
                  {p.yes_count + p.no_count} pick
                  {p.yes_count + p.no_count === 1 ? '' : 's'} · {p.yes_count} said Yes (
                  {p.yes_stake} pts) · {p.no_count} said No ({p.no_stake} pts)
                </div>
                {expanded === p.id && details[p.id] && (
                  <div data-testid="picks-detail" style={{ marginTop: 6 }}>
                    {details[p.id].picks_visible ? (
                      <ul style={{ margin: '4px 0', paddingLeft: '1.2rem' }}>
                        {details[p.id].picks.map((pick) => {
                          const correct = pick.was_correct
                          const swing =
                            correct === null || correct === undefined
                              ? null
                              : correct
                                ? `+${pick.stake}`
                                : `-${pick.stake}`
                          const mine = pick.user_id === userId
                          return (
                            <li
                              key={pick.id}
                              data-testid="pick-item"
                              style={mine ? { fontWeight: 700 } : undefined}
                            >
                              {pick.nickname} — {pick.side.toUpperCase()} (stake{' '}
                              {pick.stake})
                              {swing && (
                                <span
                                  style={{
                                    color: correct ? '#137333' : '#c5221f',
                                    marginLeft: 4,
                                  }}
                                >
                                  {correct ? '✓' : '✗'} {swing}
                                </span>
                              )}
                              {swing && mine && (
                                <span style={{ color: correct ? '#137333' : '#c5221f' }}>
                                  {' '}
                                  — that's you: {correct ? 'you were right!' : 'wrong'} (
                                  {swing})
                                </span>
                              )}
                            </li>
                          )
                        })}
                      </ul>
                    ) : p.status === 'open' ? (
                      <p style={{ margin: '4px 0', fontStyle: 'italic' }}>
                        Make your pick to see what everyone chose.
                      </p>
                    ) : null}
                  </div>
                )}
                {p.status === 'open' && (
                  <form
                    onSubmit={(e) => handlePick(e, p.id)}
                    style={{ display: 'flex', gap: 8, marginTop: 6 }}
                  >
                    <select
                      value={(picks[p.id] || {}).side || 'yes'}
                      onChange={(e) => updatePickForm(p.id, 'side', e.target.value)}
                    >
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                    <input
                      type="number"
                      min="0"
                      max="1000000"
                      step="1"
                      placeholder="0"
                      value={(picks[p.id] || {}).stake ?? ''}
                      onChange={(e) => updatePickForm(p.id, 'stake', e.target.value)}
                      style={{ width: 70 }}
                    />
                    <button type="submit" disabled={!!saving[p.id]}>
                      {saving[p.id] ? 'Saving…' : 'Pick'}
                    </button>
                  </form>
                )}
                {p.creator_id === userId && p.status === 'open' && (
                  <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
                    <button onClick={() => handleResolve(p.id, 'yes')}>Resolve Yes</button>
                    <button onClick={() => handleResolve(p.id, 'no')}>Resolve No</button>
                  </div>
                )}
              </li>
            ))}
          </ul>

          <h4>Leaderboard</h4>
          <table data-testid="leaderboard" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left' }}>
                <th style={{ padding: '0 12px 4px 0' }}>Member</th>
                <th style={{ padding: '0 12px 4px 0' }}>Points</th>
                <th style={{ padding: '0 12px 4px 0' }}>Correct</th>
                <th style={{ padding: '0 12px 4px 0' }}>Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((e) => (
                <tr key={e.user_id}>
                  <td style={{ padding: '2px 12px 2px 0' }}>{e.nickname}</td>
                  <td style={{ padding: '2px 12px 2px 0' }}>{e.points}</td>
                  <td style={{ padding: '2px 12px 2px 0' }}>
                    {e.correct}/{e.total}
                  </td>
                  <td style={{ padding: '2px 12px 2px 0' }}>
                    {(e.accuracy * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
    </section>
  )
}
