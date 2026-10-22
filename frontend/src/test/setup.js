import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

/**
 * Fake WebSocket. It records every instance so a test can grab the live one,
 * and `receive()` pushes a server message into the app's onmessage handler.
 */
export class FakeWebSocket {
  static instances = []

  constructor(url) {
    this.url = url
    this.sent = []
    this.closed = false
    this.onopen = null
    this.onmessage = null
    this.onclose = null
    this.onerror = null
    FakeWebSocket.instances.push(this)
  }

  send(data) {
    this.sent.push(data)
  }

  close() {
    this.closed = true
  }

  /** Push a message from the "server" into the app. */
  receive(message) {
    const data = typeof message === 'string' ? message : JSON.stringify(message)
    this.onmessage?.({ data })
  }
}

/**
 * The single fetch mock used by the whole suite. Tests install a handler via
 * setFetchHandler(); until then any call is an explicit failure, so a test
 * can never reach the real network.
 */
export const fetchCalls = []
let handler = null

export function setFetchHandler(fn) {
  handler = fn
}

globalThis.fetch = vi.fn(async (url, init) => {
  const call = { url, init, handled: false, unmatched: false }
  fetchCalls.push(call)
  if (!handler) {
    call.unmatched = true
    throw new Error(`UNMOCKED_FETCH: ${url}`)
  }
  return handler(url, init, call)
})

globalThis.WebSocket = FakeWebSocket

if (!globalThis.matchMedia) {
  globalThis.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false
    },
  })
}
if (!window.matchMedia) {
  window.matchMedia = globalThis.matchMedia
}

beforeEach(() => {
  fetchCalls.length = 0
  setFetchHandler(null)
  FakeWebSocket.instances.length = 0
  localStorage.clear()
})

afterEach(() => {
  const unmatched = fetchCalls.filter((c) => c.unmatched)
  cleanup()
  localStorage.clear()
  if (unmatched.length) {
    throw new Error(
      `Test made an unmocked network call: ${unmatched
        .map((c) => c.url)
        .join(', ')}`,
    )
  }
})
