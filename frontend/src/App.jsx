import { useCallback, useEffect, useState } from 'react'

const API = 'http://localhost:8000'
const TOKEN_KEY = 'frager_token'

export default function App() {
  const [health, setHealth] = useState('loading…')
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
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
      const res = await fetch(`${API}/api/auth/me`, {
        headers: { Authorization: `Bearer ${tok}` },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setUser(await res.json())
      setError('')
    } catch (err) {
      localStorage.removeItem(TOKEN_KEY)
      setToken(null)
      setUser(null)
      setError(`Session invalid, please log in again (${err.message})`)
    }
  }, [])

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => setHealth(data.status === 'ok' ? 'Backend: ok' : `Backend: ${data.status}`))
      .catch((err) => setHealth(`Backend: unreachable (${err.message})`))
  }, [])

  useEffect(() => {
    if (token) loadMe(token)
  }, [token, loadMe])

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      const res = await fetch(`${API}/api/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try {
          detail = (await res.json()).detail || detail
        } catch {}
        throw new Error(detail)
      }
      const data = await res.json()
      localStorage.setItem(TOKEN_KEY, data.access_token)
      setPassword('')
      setToken(data.access_token)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem', maxWidth: 420 }}>
      <h1>Frager</h1>
      <p data-testid="backend-status">{health}</p>

      {user ? (
        <section>
          <p data-testid="user-status">Logged in as {user.email}</p>
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
  const [name, setName] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [newLeague, setNewLeague] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')

  const auth = { Authorization: `Bearer ${token}` }

  const loadLeagues = useCallback(async () => {
    const res = await fetch(`${API}/api/leagues`, { headers: auth })
    if (res.ok) setLeagues(await res.json())
  }, [token])

  useEffect(() => {
    loadLeagues()
  }, [loadLeagues])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      const res = await fetch(`${API}/api/leagues`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const league = await res.json()
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
      const res = await fetch(`${API}/api/leagues/join`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: joinCode }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
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
  const [question, setQuestion] = useState('')
  const [error, setError] = useState('')
  const [picks, setPicks] = useState({})

  const auth = { Authorization: `Bearer ${token}` }

  const loadPredictions = useCallback(async () => {
    const res = await fetch(`${API}/api/leagues/${league.id}/predictions`, {
      headers: auth,
    })
    if (res.ok) setPredictions(await res.json())
    else setError((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`)
  }, [league.id, token])

  const loadLeaderboard = useCallback(async () => {
    const res = await fetch(`${API}/api/leagues/${league.id}/leaderboard`, {
      headers: auth,
    })
    if (res.ok) setLeaderboard(await res.json())
  }, [league.id, token])

  useEffect(() => {
    loadPredictions()
    loadLeaderboard()
  }, [loadPredictions, loadLeaderboard])

  function updatePickForm(predictionId, field, value) {
    setPicks((prev) => ({
      ...prev,
      [predictionId]: { side: 'yes', stake: 0, ...prev[predictionId], [field]: value },
    }))
  }

  async function handlePost(e) {
    e.preventDefault()
    setError('')
    try {
      const res = await fetch(`${API}/api/leagues/${league.id}/predictions`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      setQuestion('')
      await loadPredictions()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handlePick(e, predictionId) {
    e.preventDefault()
    setError('')
    const form = picks[predictionId] || { side: 'yes', stake: 0 }
    try {
      const res = await fetch(`${API}/api/predictions/${predictionId}/pick`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ side: form.side, stake: Number(form.stake) || 0 }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      await loadPredictions()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleResolve(predictionId, outcome) {
    setError('')
    try {
      const res = await fetch(`${API}/api/predictions/${predictionId}/resolve`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      await Promise.all([loadPredictions(), loadLeaderboard()])
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

      <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 12 }}>
        {predictions.map((p) => (
          <li key={p.id} data-testid="prediction-item" style={{ border: '1px solid #ccc', padding: 8 }}>
            <div>
              <strong>{p.question}</strong>{' '}
              <em>
                ({p.status}
                {p.resolved_outcome ? `, resolved ${p.resolved_outcome.toUpperCase()}` : ''})
              </em>
            </div>
            <div data-testid="prediction-counts">
              Yes: {p.yes_count} · No: {p.no_count}
            </div>
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
                  placeholder="stake"
                  value={(picks[p.id] || {}).stake ?? 0}
                  onChange={(e) => updatePickForm(p.id, 'stake', e.target.value)}
                  style={{ width: 70 }}
                />
                <button type="submit">Pick</button>
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
              <td style={{ padding: '2px 12px 2px 0' }}>{e.email}</td>
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

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
    </section>
  )
}
