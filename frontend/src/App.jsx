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
          <Leagues token={token} />
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

function Leagues({ token }) {
  const [leagues, setLeagues] = useState([])
  const [name, setName] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [newLeague, setNewLeague] = useState(null)
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
          <li key={l.id} data-testid="league-item">
            {l.name} — {l.member_count} member{l.member_count === 1 ? '' : 's'} · code{' '}
            <code>{l.invite_code}</code>
          </li>
        ))}
      </ul>

      {error && <p style={{ color: 'crimson' }}>{error}</p>}
    </section>
  )
}
