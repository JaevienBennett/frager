import { describe, expect, it, vi } from 'vitest'

import { jsonResponse, mockFetch } from '../test/helpers'
import {
  API,
  NETWORK_ERROR,
  fetchJson,
  fetchJsonWithRetry,
  getRefreshToken,
} from './api'

describe('fetchJson', () => {
  it('throws the backend detail message for a failed request', async () => {
    mockFetch(async () =>
      jsonResponse({ detail: 'League not found' }, { status: 404 }),
    )

    await expect(fetchJson(`${API}/api/leagues/9`)).rejects.toThrow(
      'League not found',
    )
  })

  it('keeps the HTTP status on the error', async () => {
    mockFetch(async () =>
      jsonResponse({ detail: 'League not found' }, { status: 404 }),
    )

    await expect(fetchJson(`${API}/api/leagues/9`)).rejects.toMatchObject({
      status: 404,
    })
  })

  it('falls back to a generic message when the body has no detail', async () => {
    mockFetch(async () => jsonResponse({}, { status: 500 }))

    await expect(fetchJson(`${API}/api/leagues`)).rejects.toThrow(
      'Request failed (HTTP 500)',
    )
  })

  it('turns a network failure into the friendly message', async () => {
    mockFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(fetchJson(`${API}/api/leagues`)).rejects.toThrow(NETWORK_ERROR)
  })

  it('never leaks the raw browser error to the user', async () => {
    mockFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    const err = await fetchJson(`${API}/api/leagues`).catch((e) => e)
    expect(err.message).not.toContain('Failed to fetch')
    expect(err.message).toContain("Couldn't reach the server")
  })

  it('refreshes once and retries with the new access token', async () => {
    localStorage.setItem('frager_refresh', 'old-refresh')
    const calls = []
    mockFetch(async (url, init) => {
      calls.push({ url, init })
      if (url.endsWith('/api/auth/refresh')) {
        return jsonResponse({
          access_token: 'new-access',
          refresh_token: 'new-refresh',
        })
      }
      const seen = calls.filter((c) => c.url === url).length
      if (seen === 1) {
        return jsonResponse({ detail: 'Not authenticated' }, { status: 401 })
      }
      return jsonResponse({ id: 1, name: 'League' })
    })

    const data = await fetchJson(`${API}/api/leagues`, {
      headers: { 'X-Test': 'yes' },
    })
    expect(data).toEqual({ id: 1, name: 'League' })

    const leagues = calls.filter((c) => c.url === `${API}/api/leagues`)
    expect(leagues).toHaveLength(2)
    expect(leagues[0].init.headers.Authorization).toBeUndefined()
    expect(leagues[1].init.headers.Authorization).toBe('Bearer new-access')
    expect(leagues[1].init.headers['X-Test']).toBe('yes')

    // exactly one refresh call
    expect(calls.filter((c) => c.url.endsWith('/api/auth/refresh'))).toHaveLength(
      1,
    )
    // and the rotated refresh token replaced the old one
    expect(getRefreshToken()).toBe('new-refresh')
  })

  it('does not retry a 401 when there is no refresh token', async () => {
    const calls = []
    mockFetch(async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({ detail: 'Not authenticated' }, { status: 401 })
    })

    await expect(fetchJson(`${API}/api/leagues`)).rejects.toThrow(
      'Not authenticated',
    )
    expect(calls).toHaveLength(1)
  })

  it('does not retry a 401 on an auth endpoint', async () => {
    const calls = []
    localStorage.setItem('frager_refresh', 'old-refresh')
    mockFetch(async (url, init) => {
      calls.push({ url, init })
      return jsonResponse({ detail: 'Incorrect email or password' }, { status: 401 })
    })

    await expect(fetchJson(`${API}/api/auth/login`)).rejects.toThrow(
      'Incorrect email or password',
    )
    expect(calls).toHaveLength(1)
  })
})

describe('fetchJsonWithRetry', () => {
  it('returns the first successful response', async () => {
    let n = 0
    mockFetch(async () => {
      n += 1
      return jsonResponse({ id: 1 })
    })

    await expect(fetchJsonWithRetry(`${API}/api/leagues`)).resolves.toEqual({
      id: 1,
    })
    expect(n).toBe(1)
  })

  it('retries a network error and then succeeds', async () => {
    vi.useFakeTimers()
    try {
      let n = 0
      mockFetch(async () => {
        n += 1
        if (n < 3) throw new TypeError('Failed to fetch')
        return jsonResponse({ id: 1 })
      })

      const promise = fetchJsonWithRetry(`${API}/api/leagues`)
      await vi.runAllTimersAsync()
      await expect(promise).resolves.toEqual({ id: 1 })
      expect(n).toBe(3)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not retry a normal API error', async () => {
    let n = 0
    mockFetch(async () => {
      n += 1
      return jsonResponse({ detail: 'League not found' }, { status: 404 })
    })

    await expect(fetchJsonWithRetry(`${API}/api/leagues`)).rejects.toThrow(
      'League not found',
    )
    expect(n).toBe(1)
  })
})
