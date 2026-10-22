// Session + HTTP helpers, moved verbatim out of App.jsx so they can be
// unit tested. Behaviour is unchanged: same names, same constants, same code.

export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const TOKEN_KEY = 'frager_token'
export const REFRESH_KEY = 'frager_refresh'
export const REQUEST_TIMEOUT_MS = 60000
export const NETWORK_ERROR =
  "Couldn't reach the server. It may be waking up — please try again in a moment."
export const WAKING_UP = 'Waking up the server…'

let refreshPromise = null

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY)
}

export function storeSession(accessToken, refreshToken) {
  localStorage.setItem(TOKEN_KEY, accessToken)
  if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken)
  else localStorage.removeItem(REFRESH_KEY)
  window.dispatchEvent(
    new CustomEvent('frager:tokens', { detail: { token: accessToken } }),
  )
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export function isAuthAttempt(url) {
  return /\/api\/auth\/(login|signup|refresh)$/.test(url)
}

export async function refreshSession() {
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

export async function fetchJson(url, options = {}, retryAuth = true) {
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
