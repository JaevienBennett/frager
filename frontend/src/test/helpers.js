import { FakeWebSocket, fetchCalls, setFetchHandler } from './setup'

/** Build a minimal Response-like object. */
export function jsonResponse(body, { status = 200, ok } = {}) {
  return {
    ok: ok ?? (status >= 200 && status < 300),
    status,
    json: async () => body,
  }
}

/** Install a single handler that answers every fetch call. */
export function mockFetch(handler) {
  setFetchHandler(handler)
  return fetchCalls
}

/**
 * Install a router: the first route whose `match` (substring or RegExp) and
 * optional `method` fits answers the call. Anything else fails loudly.
 */
export function routeFetch(routes) {
  setFetchHandler(async (url, init, call) => {
    for (const route of routes) {
      const matched =
        typeof route.match === 'string'
          ? url.includes(route.match)
          : route.match.test(url)
      if (!matched) continue
      if (
        route.method &&
        (init?.method || 'GET').toUpperCase() !== route.method.toUpperCase()
      ) {
        continue
      }
      call.handled = true
      return route.respond(url, init)
    }
    call.unmatched = true
    throw new Error(`UNMOCKED_FETCH: ${url}`)
  })
  return fetchCalls
}

/** The most recently created socket. */
export function lastSocket() {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
}

/** Push a server message into a socket. */
export function deliver(socket, message) {
  socket.receive(message)
}
