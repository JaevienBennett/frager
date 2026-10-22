import { useCallback, useEffect, useRef, useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TOKEN_KEY = 'frager_token'
const REFRESH_KEY = 'frager_refresh'
const REQUEST_TIMEOUT_MS = 60000
const NETWORK_ERROR =
  "Couldn't reach the server. It may be waking up — please try again in a moment."
const WAKING_UP = 'Waking up the server…'

let refreshPromise = null

function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY)
}

function storeSession(accessToken, refreshToken) {
  localStorage.setItem(TOKEN_KEY, accessToken)
  if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken)
  else localStorage.removeItem(REFRESH_KEY)
  window.dispatchEvent(
    new CustomEvent('frager:tokens', { detail: { token: accessToken } }),
  )
}

function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

function isAuthAttempt(url) {
  return /\/api\/auth\/(login|signup|refresh)$/.test(url)
}

async function refreshSession() {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    for (let attempt = 0; attempt < 2; attempt++) {
      const refreshToken = getRefreshToken()
      if (!refreshToken) throw new Error('No refresh token')
      let res
      try {
        res = await fetch(`${API}/api/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
      } catch {
        throw new Error(NETWORK_ERROR)
      }
      if (res.ok) {
        const data = await res.json()
        storeSession(data.access_token, data.refresh_token)
        return data.access_token
      }
      const current = getRefreshToken()
      if (current && current !== refreshToken) {
        // Another tab rotated the token while this request was in flight.
        continue
      }
      clearSession()
      window.dispatchEvent(new Event('frager:auth-expired'))
      throw new Error('Session expired, please log in again.')
    }
    throw new Error('Session expired, please log in again.')
  })().finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

async function fetchJson(url, options = {}, retryAuth = true) {
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
  if (
    res.status === 401 &&
    retryAuth &&
    !isAuthAttempt(url) &&
    getRefreshToken()
  ) {
    try {
      const token = await refreshSession()
      const headers = {
        ...(options.headers || {}),
        Authorization: `Bearer ${token}`,
      }
      return await fetchJson(url, { ...options, headers }, false)
    } catch (err) {
      if (err.message === NETWORK_ERROR) throw err
    }
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

function Logo({ size = 26 }) {
  return (
    <svg
      className="logo"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label="Frager"
    >
      <circle cx="16" cy="16" r="14" fill="var(--accent)" />
      <circle cx="16" cy="16" r="14" stroke="var(--accent-hover)" strokeWidth="2" />
      <circle
        cx="16"
        cy="16"
        r="9.5"
        stroke="#fff"
        strokeWidth="2"
        strokeDasharray="3 3"
        opacity="0.9"
      />
      <text
        x="16"
        y="21.5"
        fontSize="14"
        fontWeight="800"
        fill="#fff"
        textAnchor="middle"
        fontFamily="inherit"
      >
        ?
      </text>
    </svg>
  )
}

function Brand({ hero = false }) {
  return (
    <div className={hero ? 'brand brand-hero' : 'brand'}>
      <Logo size={hero ? 34 : 26} />
      <h1 className="wordmark">Frager</h1>
    </div>
  )
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(
    () => !!(localStorage.getItem(TOKEN_KEY) || getRefreshToken()),
  )
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [mode, setMode] = useState('login')
  const [error, setError] = useState('')

  const logout = useCallback(async () => {
    const refreshToken = getRefreshToken()
    clearSession()
    setToken(null)
    setUser(null)
    setError('')
    if (refreshToken) {
      try {
        await fetchJson(`${API}/api/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
      } catch {}
    }
  }, [])

  async function logoutAll() {
    if (
      !window.confirm(
        'Log out of all devices? Every session will need to sign in again.',
      )
    ) {
      return
    }
    setError('')
    try {
      await fetchJson(`${API}/api/auth/logout-all`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      clearSession()
      setToken(null)
      setUser(null)
    } catch (err) {
      if (err.status !== 401) setError(err.message)
    }
  }

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
        clearSession()
        setToken(null)
        setUser(null)
        setError('Session expired, please log in again.')
      }
    } finally {
      setBooting(false)
    }
  }, [])

  useEffect(() => {
    function onTokens(e) {
      if (e.detail?.token) setToken(e.detail.token)
    }
    function onExpired() {
      setToken(null)
      setUser(null)
      setError('Session expired, please log in again.')
    }
    window.addEventListener('frager:tokens', onTokens)
    window.addEventListener('frager:auth-expired', onExpired)
    return () => {
      window.removeEventListener('frager:tokens', onTokens)
      window.removeEventListener('frager:auth-expired', onExpired)
    }
  }, [])

  useEffect(() => {
    if (token) loadMe(token)
    else if (getRefreshToken()) {
      refreshSession()
        .then((tok) => setToken(tok))
        .catch((err) => {
          if (err.message === NETWORK_ERROR) setError(err.message)
          setBooting(false)
        })
    } else {
      setBooting(false)
    }
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
      storeSession(data.access_token, data.refresh_token)
      setPassword('')
      setNickname('')
      setToken(data.access_token)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="app">
      {user && (
        <header className="header">
          <div className="header-inner">
            <Brand />
            <div className="header-right">
              <span className="header-user" data-testid="user-status">
                Logged in as {user.nickname}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={logoutAll}>
                Log out all
              </button>
              <button className="btn btn-secondary btn-sm" onClick={logout}>
                Log out
              </button>
            </div>
          </div>
        </header>
      )}

      <main>
        <div className="container">
          {booting ? (
            <>
              <Brand hero />
              <p className="muted center">{WAKING_UP}</p>
            </>
          ) : user ? (
            <section className="stack">
              <Leagues token={token} userId={user.id} />
            </section>
          ) : (
            <>
              <Brand hero />
              <form className="card form auth-card" onSubmit={submit}>
                <h2 className="section-title">
                  {mode === 'login' ? 'Log in' : 'Sign up'}
                </h2>
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
              placeholder="password (8+ chars)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
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
            </>
          )}

          {error && <p className="error">{error}</p>}
        </div>
      </main>
    </div>
  )
}

function Leagues({ token, userId }) {
  const [leagues, setLeagues] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [name, setName] = useState('')
  const [joinCode, setJoinCode] = useState('')
  const [joinFromLink, setJoinFromLink] = useState(false)
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

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('join')
    if (code) {
      setJoinCode(code.trim())
      setJoinFromLink(true)
    }
  }, [])

  function handleLeagueUpdated(updated) {
    setLeagues((prev) => prev.map((l) => (l.id === updated.id ? updated : l)))
    setSelected(updated)
  }

  function handleLeagueDeleted(id) {
    setLeagues((prev) => prev.filter((l) => l.id !== id))
    setSelected(null)
  }

  function handleLeftLeague() {
    setSelected(null)
    loadLeagues()
  }

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    const trimmed = name.trim()
    if (!trimmed) {
      setError('League name is required.')
      return
    }
    if (trimmed.length > 100) {
      setError('League name must be 100 characters or fewer.')
      return
    }
    try {
      const league = await fetchJson(`${API}/api/leagues`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
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
        body: JSON.stringify({ invite_code: joinCode.trim() }),
      })
      setJoinCode('')
      setJoinFromLink(false)
      if (window.location.search) {
        window.history.replaceState({}, '', window.location.pathname)
      }
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
          maxLength={100}
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
          onChange={(e) => {
            setJoinCode(e.target.value)
            setJoinFromLink(false)
          }}
          required
        />
        <button type="submit" className="btn btn-secondary">
          Join league
        </button>
      </form>
      {joinFromLink && (
        <p className="hint" data-testid="join-hint">
          Invite code filled in from your link — click “Join league”.
        </p>
      )}

      {newLeague && (
        <p className="success" data-testid="new-league">
          Created <strong>{newLeague.name}</strong> — invite code:{' '}
          <code className="code">{newLeague.invite_code}</code>
        </p>
      )}

      {!loaded ? (
        <p className="muted">{WAKING_UP}</p>
      ) : leagues.length === 0 ? (
        <div className="card empty-state">
          <span className="empty-icon" aria-hidden="true">
            🎲
          </span>
          <p>No leagues yet — create one and invite friends.</p>
        </div>
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
          onUpdated={handleLeagueUpdated}
          onDeleted={handleLeagueDeleted}
          onLeft={handleLeftLeague}
        />
      )}
    </section>
  )
}

function LeagueView({ token, userId, league, onBack, onUpdated, onDeleted, onLeft }) {
  const [predictions, setPredictions] = useState([])
  const [leaderboard, setLeaderboard] = useState([])
  const [details, setDetails] = useState({})
  const [expanded, setExpanded] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [question, setQuestion] = useState('')
  const [gameUrl, setGameUrl] = useState('')
  const [error, setError] = useState('')
  const [picks, setPicks] = useState({})
  const [saving, setSaving] = useState({})
  const [pickErrors, setPickErrors] = useState({})
  const [pickSaved, setPickSaved] = useState({})
  const [renaming, setRenaming] = useState(false)
  const [newName, setNewName] = useState(league.name)
  const [actionError, setActionError] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const [inviteCopied, setInviteCopied] = useState(false)
  const [transferOpen, setTransferOpen] = useState(false)
  const [members, setMembers] = useState([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [transferTarget, setTransferTarget] = useState(null)
  const [transferError, setTransferError] = useState('')
  const savedTimers = useRef({})
  const detailRequested = useRef({})
  const wsRef = useRef(null)
  const wsReconnectRef = useRef(null)
  const leagueRef = useRef(league)
  const onUpdatedRef = useRef(onUpdated)

  useEffect(() => {
    leagueRef.current = league
    onUpdatedRef.current = onUpdated
  })

  const auth = { Authorization: `Bearer ${token}` }
  const isOwner = league.owner_id === userId
  const inviteUrl = `${window.location.origin}${window.location.pathname}?join=${encodeURIComponent(
    league.invite_code,
  )}`

  useEffect(() => {
    setNewName(league.name)
    setRenaming(false)
    setActionError('')
  }, [league.id, league.name])

  async function handleRename(e) {
    e.preventDefault()
    setActionError('')
    const trimmed = newName.trim()
    if (!trimmed) {
      setActionError('League name is required.')
      return
    }
    if (trimmed.length > 100) {
      setActionError('League name must be 100 characters or fewer.')
      return
    }
    setActionBusy(true)
    try {
      const updated = await fetchJson(`${API}/api/leagues/${league.id}`, {
        method: 'PATCH',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
      })
      onUpdated?.(updated)
    } catch (err) {
      setActionError(err.message)
    } finally {
      setActionBusy(false)
    }
  }

  async function handleDelete() {
    if (
      !window.confirm(
        `Delete "${league.name}"? This removes its predictions and picks for everyone, and cannot be undone.`,
      )
    ) {
      return
    }
    setActionError('')
    setActionBusy(true)
    try {
      await fetchJson(`${API}/api/leagues/${league.id}`, {
        method: 'DELETE',
        headers: auth,
      })
      onDeleted?.(league.id)
    } catch (err) {
      setActionError(err.message)
      setActionBusy(false)
    }
  }

  async function handleLeave() {
    if (!window.confirm(`Leave "${league.name}"?`)) return
    setActionError('')
    setActionBusy(true)
    try {
      await fetchJson(`${API}/api/leagues/${league.id}/leave`, {
        method: 'POST',
        headers: auth,
      })
      onLeft?.()
    } catch (err) {
      setActionError(err.message)
      setActionBusy(false)
    }
  }

  async function copyInvite() {
    try {
      await navigator.clipboard.writeText(inviteUrl)
      setInviteCopied(true)
      setTimeout(() => setInviteCopied(false), 2000)
    } catch {
      setActionError('Could not copy the link — select it and copy manually.')
    }
  }

  async function openTransfer() {
    setTransferOpen(true)
    setTransferTarget(null)
    setTransferError('')
    setMembersLoading(true)
    try {
      const data = await fetchJson(`${API}/api/leagues/${league.id}/members`, {
        headers: auth,
      })
      setMembers(data)
    } catch (err) {
      setTransferError(err.message)
    } finally {
      setMembersLoading(false)
    }
  }

  async function handleTransfer() {
    if (!transferTarget) {
      setTransferError('Pick the member who should take over.')
      return
    }
    setTransferError('')
    setActionBusy(true)
    try {
      const updated = await fetchJson(
        `${API}/api/leagues/${league.id}/transfer`,
        {
          method: 'POST',
          headers: { ...auth, 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_owner_id: transferTarget }),
        },
      )
      setTransferOpen(false)
      onUpdated?.(updated)
    } catch (err) {
      setTransferError(err.message)
    } finally {
      setActionBusy(false)
    }
  }

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

  useEffect(() => {
    let reconnectAttempts = 0
    let closed = false

    function connect() {
      if (closed) return
      try {
        const wsBase = API.replace(/^http/, 'ws')
        const ws = new WebSocket(
          `${wsBase}/ws/leagues/${league.id}?token=${encodeURIComponent(token)}`,
        )
        wsRef.current = ws
        ws.onopen = () => {
          reconnectAttempts = 0
        }
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data)
            if (msg.type === 'prediction_created') {
              loadPredictions()
              loadLeaderboard()
              return
            }
            if (msg.type === 'pick_updated') {
              loadPredictions()
              if (msg.prediction_id) {
                loadDetail(msg.prediction_id)
              }
              loadLeaderboard()
              return
            }
            if (msg.type === 'prediction_resolved') {
              loadPredictions()
              loadLeaderboard()
              if (msg.prediction_id) {
                loadDetail(msg.prediction_id)
              }
              return
            }
            if (msg.type === 'leaderboard_updated') {
              loadLeaderboard()
              return
            }
            if (msg.type === 'league_updated') {
              if (typeof msg.owner_id === 'number') {
                onUpdatedRef.current?.({
                  ...leagueRef.current,
                  owner_id: msg.owner_id,
                })
              }
              loadLeaderboard()
            }
          } catch {}
        }
        ws.onclose = () => {
          if (closed) return
          reconnectAttempts += 1
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 5000)
          wsReconnectRef.current = setTimeout(connect, delay)
        }
        ws.onerror = () => {
          try {
            ws.close()
          } catch {}
        }
      } catch {
        reconnectAttempts += 1
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 5000)
        wsReconnectRef.current = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closed = true
      if (wsReconnectRef.current) {
        clearTimeout(wsReconnectRef.current)
      }
      if (wsRef.current) {
        try {
          wsRef.current.close()
        } catch {}
      }
    }
  }, [league.id, token, loadPredictions, loadLeaderboard, loadDetail])

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
    const trimmed = question.trim()
    if (!trimmed) {
      setError('Enter a question.')
      return
    }
    if (trimmed.length > 500) {
      setError('Question must be 500 characters or fewer.')
      return
    }
    try {
      await fetchJson(`${API}/api/leagues/${league.id}/predictions`, {
        method: 'POST',
        headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed, game_url: gameUrl || null }),
      })
      setQuestion('')
      setGameUrl('')
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
      <div className="league-head">
        <h3 className="section-title">{league.name}</h3>
        <div className="row">
          {isOwner && !renaming && (
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              onClick={() => {
                setNewName(league.name)
                setRenaming(true)
              }}
              data-testid="rename-league"
            >
              Rename
            </button>
          )}
          {isOwner && (
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              onClick={openTransfer}
              disabled={actionBusy}
              data-testid="transfer-league"
            >
              Transfer ownership
            </button>
          )}
          {isOwner && (
            <button
              className="btn btn-danger btn-sm"
              type="button"
              onClick={handleDelete}
              disabled={actionBusy}
              data-testid="delete-league"
            >
              Delete league
            </button>
          )}
          {!isOwner && (
            <button
              className="btn btn-danger btn-sm"
              type="button"
              onClick={handleLeave}
              disabled={actionBusy}
              data-testid="leave-league"
            >
              Leave league
            </button>
          )}
        </div>
      </div>

      {renaming && (
        <form className="form-row" onSubmit={handleRename}>
          <input
            className="input"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            maxLength={100}
            aria-label="League name"
            required
          />
          <button type="submit" className="btn btn-primary" disabled={actionBusy}>
            Save name
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setRenaming(false)}
          >
            Cancel
          </button>
        </form>
      )}

      <div className="invite-row">
        <span className="muted">Invite link</span>
        <input
          className="input"
          readOnly
          value={inviteUrl}
          onFocus={(e) => e.target.select()}
          aria-label="Invite link"
          data-testid="invite-link"
        />
        <button
          type="button"
          className="btn btn-secondary"
          onClick={copyInvite}
          data-testid="copy-invite"
        >
          {inviteCopied ? 'Copied!' : 'Copy link'}
        </button>
      </div>
      <p className="hint">
        Anyone with this link can join. Invite code:{' '}
        <span className="code">{league.invite_code}</span>
      </p>

      {actionError && <p className="error">{actionError}</p>}

      <form className="form-row" onSubmit={handlePost} style={{ flexWrap: 'wrap' }}>
        <input
          className="input"
          placeholder="Ask a yes/no question…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={500}
          required
        />
        <input
          className="input"
          placeholder="ESPN NFL game link (optional)"
          value={gameUrl}
          onChange={(e) => setGameUrl(e.target.value)}
        />
        <button type="submit" className="btn btn-primary">
          Post prediction
        </button>
      </form>
      {gameUrl && (
        <p className="muted" style={{ marginTop: '-0.5rem' }}>
          Linked to NFL — will auto-resolve
        </p>
      )}

      {!loaded ? (
        <p className="muted">{WAKING_UP}</p>
      ) : (
        <>
          {predictions.length === 0 ? (
            <div className="card empty-state">
              <span className="empty-icon" aria-hidden="true">
                🎯
              </span>
              <p>No predictions yet. Post the first one!</p>
            </div>
          ) : (
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
                  <span className="chip chip-sm">
                    <span className="coin" aria-hidden="true" />
                    {p.yes_stake}
                  </span>{' '}
                  pts) · {p.no_count} said No (
                  <span className="chip chip-sm">
                    <span className="coin" aria-hidden="true" />
                    {p.no_stake}
                  </span>{' '}
                  pts)
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
                      <span className="chip chip-sm">
                        <span className="coin" aria-hidden="true" />
                        {mine.stake}
                      </span>{' '}
                      pts
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
                    <div className="segmented" role="group" aria-label="Pick a side">
                      <button
                        type="button"
                        className={`segment segment-yes ${
                          ((picks[p.id] || {}).side || 'yes') === 'yes' ? 'active' : ''
                        }`}
                        aria-pressed={((picks[p.id] || {}).side || 'yes') === 'yes'}
                        onClick={() => updatePickForm(p.id, 'side', 'yes')}
                      >
                        Yes
                      </button>
                      <button
                        type="button"
                        className={`segment segment-no ${
                          ((picks[p.id] || {}).side || 'yes') === 'no' ? 'active' : ''
                        }`}
                        aria-pressed={((picks[p.id] || {}).side || 'yes') === 'no'}
                        onClick={() => updatePickForm(p.id, 'side', 'no')}
                      >
                        No
                      </button>
                    </div>
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
          )}

          <div className="card leaderboard">
            <h4 className="section-title">Leaderboard</h4>
            <div className="table-wrap">
              <table className="table" data-testid="leaderboard">
                <thead>
                  <tr>
                    <th className="rank">#</th>
                    <th>Member</th>
                    <th className="num">Points</th>
                    <th className="num" title="Record (correct / total picks)">
                      Record
                    </th>
                    <th className="num">Accuracy</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.map((e, idx) => {
                    const rank = idx + 1
                    const medal =
                      rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : null
                    return (
                      <tr
                        key={e.user_id}
                        className={e.user_id === userId ? 'me' : undefined}
                      >
                        <td className="rank">{medal ?? rank}</td>
                        <td>
                          {e.nickname}
                          {e.user_id === league.owner_id && (
                            <span className="owner-tag" data-testid="owner-badge">
                              Owner
                            </span>
                          )}
                        </td>
                        <td className="num">{e.points}</td>
                        <td className="num">
                          {e.correct}/{e.total}
                        </td>
                        <td className="num">
                          {(e.accuracy * 100).toFixed(0)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {transferOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) setTransferOpen(false)
          }}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Transfer ownership"
            data-testid="transfer-modal"
          >
            <h4>Transfer ownership</h4>
            <p className="hint">
              The new owner can rename and delete the league. You stay a member
              and can leave the league whenever you like.
            </p>
            {membersLoading ? (
              <p className="muted">Loading members…</p>
            ) : members.length <= 1 ? (
              <p className="muted">
                You are the only member — invite someone before handing the
                league over.
              </p>
            ) : (
              <ul className="modal-list">
                {members.map((m) => (
                  <li key={m.user_id}>
                    <button
                      type="button"
                      className={`modal-option${
                        transferTarget === m.user_id ? ' selected' : ''
                      }`}
                      onClick={() => setTransferTarget(m.user_id)}
                      disabled={m.is_owner}
                      data-testid={`transfer-option-${m.user_id}`}
                    >
                      <span>{m.nickname}</span>
                      {m.is_owner && <span className="owner-tag">Owner</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {transferError && <p className="error">{transferError}</p>}
            <div className="row">
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleTransfer}
                disabled={actionBusy || !transferTarget}
                data-testid="confirm-transfer"
              >
                Transfer ownership
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setTransferOpen(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  )
}
