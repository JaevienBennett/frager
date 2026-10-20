import { useCallback, useEffect, useRef, useState } from 'react'

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
    const error = new Error(detail)
    error.status = res.status
    throw error
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

function pickErrorMessage(err) {
  if (err.status === 409) {
    return "This prediction was already resolved — your pick wasn't saved."
  }
  const reason = err.message
  return `Your pick was NOT saved: ${reason}${/[.!?]$/.test(reason) ? '' : '.'} Please try again.`
}

function findMyPick(detail, userId) {
  if (!detail || !detail.picks_visible) return null
  return detail.picks.find((pk) => pk.user_id === userId) || null
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
    <main className="app">
      <div className="container">
        <h1 className="app-title">Frager</h1>

        {booting ? (
          <p className="muted">{WAKING_UP}</p>
        ) : user ? (
          <section className="stack">
            <div className="row between">
              <p className="user-status" data-testid="user-status">
                Logged in as {user.nickname}
              </p>
              <button className="btn btn-secondary" onClick={logout}>
                Log out
              </button>
            </div>
            <Leagues token={token} userId={user.id} />
          </section>
        ) : (
          <form className="card form auth-card" onSubmit={submit}>
            <h2 className="section-title">{mode === 'login' ? 'Log in' : 'Sign up'}</h2>
            <input
              className="input"
              type="email"
              placeholder="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            {mode === 'signup' && (
              <input
                className="input"
                placeholder="nickname (2-24 chars)"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                required
                minLength={2}
                maxLength={24}
              />
            )}
            <input
              className="input"
              type="password"
              placeholder="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button type="submit" className="btn btn-primary">
              {mode === 'login' ? 'Log in' : 'Sign up'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}
            >
              {mode === 'login' ? 'Need an account? Sign up' : 'Have an account? Log in'}
            </button>
          </form>
        )}

        {error && <p className="error">{error}</p>}
      </div>
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
    <section className="stack">
      <h2 className="section-title">Leagues</h2>

      <form className="form-row" onSubmit={handleCreate}>
        <input
          className="input"
          placeholder="league name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <button type="submit" className="btn btn-primary">
          Create league
        </button>
      </form>

      <form className="form-row" onSubmit={handleJoin}>
        <input
          className="input"
          placeholder="invite code"
          value={joinCode}
          onChange={(e) => setJoinCode(e.target.value)}
          required
        />
        <button type="submit" className="btn btn-secondary">
          Join league
        </button>
      </form>

      {newLeague && (
        <p className="success" data-testid="new-league">
          Created <strong>{newLeague.name}</strong> — invite code:{' '}
          <code className="code">{newLeague.invite_code}</code>
        </p>
      )}

      {!loaded ? (
        <p className="muted">{WAKING_UP}</p>
      ) : (
        <ul className="league-list">
          {leagues.map((l) => (
            <li key={l.id} className="list-item" data-testid="league-item">
              <button className="link-btn" onClick={() => setSelected(l)}>
                {l.name}
              </button>{' '}
              — {l.member_count} member{l.member_count === 1 ? '' : 's'} · code{' '}
              <code className="code">{l.invite_code}</code>
            </li>
          ))}
        </ul>
      )}

      {error && <p className="error">{error}</p>}

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
  const [pickErrors, setPickErrors] = useState({})
  const [pickSaved, setPickSaved] = useState({})
  const savedTimers = useRef({})
  const detailRequested = useRef({})

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

  useEffect(() => {
    if (!loaded) return
    for (const p of predictions) {
      if (!details[p.id] && !detailRequested.current[p.id]) {
        detailRequested.current[p.id] = true
        loadDetail(p.id)
      }
    }
  }, [loaded, predictions, details, loadDetail])

  function updatePickForm(predictionId, field, value) {
    setPicks((prev) => ({
      ...prev,
      [predictionId]: { side: 'yes', stake: '', ...prev[predictionId], [field]: value },
    }))
    if (pickSaved[predictionId]) {
      clearTimeout(savedTimers.current[predictionId])
      setPickSaved((prev) => ({ ...prev, [predictionId]: null }))
    }
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
      setPickErrors((prev) => ({
        ...prev,
        [predictionId]: pickErrorMessage(err),
      }))
      return
    }
    setPickErrors((prev) => ({ ...prev, [predictionId]: null }))
    setPickSaved((prev) => ({ ...prev, [predictionId]: null }))
    clearTimeout(savedTimers.current[predictionId])
    setSaving((prev) => ({ ...prev, [predictionId]: true }))
    try {
      await fetchJsonWithRetry(
        `${API}/api/predictions/${predictionId}/pick`,
        {
          method: 'POST',
          headers: { ...auth, 'Content-Type': 'application/json' },
          body: JSON.stringify({ side: form.side, stake }),
        },
        3,
      )
      setPicks((prev) => ({ ...prev, [predictionId]: { side: form.side, stake: '' } }))
      setPickSaved((prev) => ({
        ...prev,
        [predictionId]: `✓ Pick saved: ${form.side.toUpperCase()} (${stake} pts)`,
      }))
      savedTimers.current[predictionId] = setTimeout(() => {
        setPickSaved((prev) => ({ ...prev, [predictionId]: null }))
      }, 4000)
      await Promise.all([loadPredictions(), loadDetail(predictionId)])
    } catch (err) {
      setPickErrors((prev) => ({
        ...prev,
        [predictionId]: pickErrorMessage(err),
      }))
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
    <section className="league-view" data-testid="league-view">
      <button className="btn btn-secondary" onClick={onBack}>
        ← Back to leagues
      </button>
      <h3 className="section-title">{league.name}</h3>

      <form className="form-row" onSubmit={handlePost}>
        <input
          className="input"
          placeholder="Ask a yes/no question…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          required
        />
        <button type="submit" className="btn btn-primary">
          Post prediction
        </button>
      </form>

      {!loaded ? (
        <p className="muted">{WAKING_UP}</p>
      ) : (
        <>
          <ul className="cards">
            {predictions.map((p) => (
              <li
                key={p.id}
                className="card prediction"
                data-testid="prediction-item"
              >
                <div className="prediction-head">
                  <button
                    className="link-btn"
                    onClick={() => toggleDetail(p.id)}
                    data-testid="toggle-picks"
                  >
                    {p.question}
                  </button>{' '}
                  <em
                    className={`badge ${
                      p.status === 'resolved' ? 'badge-resolved' : 'badge-open'
                    }`}
                  >
                    ({p.status})
                  </em>
                </div>
                {p.status === 'resolved' && (
                  <div
                    data-testid="outcome-banner"
                    className={`outcome-banner ${
                      p.resolved_outcome === 'yes' ? 'outcome-yes' : 'outcome-no'
                    }`}
                  >
                    Resolved: {String(p.resolved_outcome).toUpperCase()}
                  </div>
                )}
                <div className="counts muted" data-testid="prediction-counts">
                  {p.yes_count + p.no_count} pick
                  {p.yes_count + p.no_count === 1 ? '' : 's'} · {p.yes_count} said Yes (
                  {p.yes_stake} pts) · {p.no_count} said No ({p.no_stake} pts)
                </div>
                {(() => {
                  const mine = findMyPick(details[p.id], userId)
                  return mine ? (
                    <div className="mypick" data-testid="my-pick">
                      You picked:{' '}
                      <span
                        className={`side-pill ${
                          mine.side === 'yes' ? 'pill-yes' : 'pill-no'
                        }`}
                      >
                        {mine.side.toUpperCase()}
                      </span>{' '}
                      ({mine.stake} pts)
                    </div>
                  ) : null
                })()}
                {expanded === p.id && details[p.id] && (
                  <div className="picks-detail" data-testid="picks-detail">
                    {details[p.id].picks_visible ? (
                      <ul className="picks-list">
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
                              className={mine ? 'pick-item mine' : 'pick-item'}
                              data-testid="pick-item"
                            >
                              {pick.nickname} — {pick.side.toUpperCase()} (stake{' '}
                              {pick.stake})
                              {swing && (
                                <span className={correct ? 'swing ok' : 'swing bad'}>
                                  {correct ? '✓' : '✗'} {swing}
                                </span>
                              )}
                              {swing && mine && (
                                <span className={correct ? 'swing ok' : 'swing bad'}>
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
                      <p className="muted hint">
                        Make your pick to see what everyone chose.
                      </p>
                    ) : null}
                  </div>
                )}
                {p.status === 'open' && (
                  <form className="form-row" onSubmit={(e) => handlePick(e, p.id)}>
                    <select
                      className="select"
                      value={(picks[p.id] || {}).side || 'yes'}
                      onChange={(e) => updatePickForm(p.id, 'side', e.target.value)}
                    >
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                    <input
                      className="input stake"
                      type="number"
                      min="0"
                      max="1000000"
                      step="1"
                      placeholder="0"
                      value={(picks[p.id] || {}).stake ?? ''}
                      onChange={(e) => updatePickForm(p.id, 'stake', e.target.value)}
                    />
                    <button type="submit" className="btn btn-primary" disabled={!!saving[p.id]}>
                      {saving[p.id] ? 'Saving…' : 'Pick'}
                    </button>
                  </form>
                )}
                {pickErrors[p.id] && (
                  <p className="error pick-msg" data-testid="pick-error">
                    {pickErrors[p.id]}
                  </p>
                )}
                {pickSaved[p.id] && (
                  <p className="success pick-msg" data-testid="pick-saved">
                    {pickSaved[p.id]}
                  </p>
                )}
                {p.creator_id === userId && p.status === 'open' && (
                  <div className="btn-row">
                    <button className="btn btn-primary" onClick={() => handleResolve(p.id, 'yes')}>
                      Resolve Yes
                    </button>
                    <button className="btn btn-primary" onClick={() => handleResolve(p.id, 'no')}>
                      Resolve No
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>

          <div className="card leaderboard">
            <h4 className="section-title">Leaderboard</h4>
            <div className="table-wrap">
              <table className="table" data-testid="leaderboard">
                <thead>
                  <tr>
                    <th>Member</th>
                    <th className="num">Points</th>
                    <th className="num" title="Record (correct / total picks)">
                      Record
                    </th>
                    <th className="num">Accuracy</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.map((e) => (
                    <tr
                      key={e.user_id}
                      className={e.user_id === userId ? 'me' : undefined}
                    >
                      <td>{e.nickname}</td>
                      <td className="num">{e.points}</td>
                      <td className="num">
                        {e.correct}/{e.total}
                      </td>
                      <td className="num">
                        {(e.accuracy * 100).toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  )
}
