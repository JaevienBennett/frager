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
