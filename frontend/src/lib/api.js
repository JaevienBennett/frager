// Session + HTTP helpers, moved verbatim out of App.jsx so they are
// unit tested. Behaviour is unchanged: same names, same constants, same code.

export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const REQUEST_TIMEOUT_MS = 60000
export const NETWORK_ERROR =
  "Couldn't reach the server. It may be waking up — please try again in a moment."
export const WAKING_UP = 'Waking up the server…'

// Before M26 the tokens lived in localStorage. They do not any more: the
// refresh token is an httpOnly cookie the browser keeps and no script can
// read, and the access token is held in memory for as long as the tab is
// open. These two names are only kept so the leftovers can be cleared.
export const LEGACY_TOKEN_KEY = 'frager_token'
export const LEGACY_REFRESH_KEY = 'frager_refresh'

// The access token and the CSRF token live in memory only. Nothing here is
// written to disk, so a script that gets into the page has nothing to steal.
let accessToken = null
let csrfToken = null
let refreshPromise = null
// Whether we know there is a session to refresh. Without it a 401 is the
// end of the line: there is nothing to refresh with.
let sessionKnown = false

export function getAccessToken() {
  return accessToken
}

export function getCsrfToken() {
  return csrfToken
}

export function hasSession() {
  return sessionKnown
}

export function storeSession(access, csrf) {
  accessToken = access || null
  csrfToken = csrf || null
  sessionKnown = !!accessToken
  window.dispatchEvent(
    new CustomEvent('frager:tokens', { detail: { token: accessToken } }),
  )
}

export function clearSession() {
  accessToken = null
  csrfToken = null
  sessionKnown = false
  purgeLegacyTokens()
}

/** Throw away the tokens the old version kept in localStorage. */
export function purgeLegacyTokens() {
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY)
    localStorage.removeItem(LEGACY_REFRESH_KEY)
  } catch {}
}

export function isAuthAttempt(url) {
  return /\/api\/auth\/(login|signup|refresh)$/.test(url)
}

/**
 * Swap the session cookie for a new access token.
 *
 * The cookie travels with the request, so the browser has to be told to send
 * it. The server answers with a fresh cookie and a fresh access token.
 */
export async function refreshSession() {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    for (let attempt = 0; attempt < 2; attempt++) {
      let res
      try {
        res = await fetch(`${API}/api/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        })
      } catch {
        throw new Error(NETWORK_ERROR)
      }
      if (res.ok) {
        const data = await res.json()
        storeSession(data.access_token, data.csrf_token)
        return data.access_token
      }
      let detail = ''
      try {
        detail = (await res.json())?.detail || ''
      } catch {}
      if (detail === 'Refresh token already rotated' && attempt === 0) {
        // Two tabs refreshed at the same time. The loser waits for the
        // winner's cookie to land and tries once more.
        await new Promise((resolve) => setTimeout(resolve, 500))
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

function withSession(options = {}) {
  const headers = { ...(options.headers || {}) }
  // The cookie is sent on every request; the CSRF token proves to the server
  // that this request really came from the app.
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken
  return { ...options, credentials: 'include', headers }
}

export async function fetchJson(url, options = {}, retryAuth = true) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let res
  try {
    res = await fetch(url, withSession(options))
  } catch {
    throw new Error(NETWORK_ERROR)
  } finally {
    clearTimeout(timer)
  }
  if (
    res.status === 401 &&
    retryAuth &&
    !isAuthAttempt(url) &&
    sessionKnown
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

export async function fetchJsonWithRetry(url, options = {}, attempts = 3) {
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
