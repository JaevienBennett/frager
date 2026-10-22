import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import App from './App'
import { jsonResponse, routeFetch } from './test/helpers'

let user

beforeEach(() => {
  user = userEvent.setup()
})

async function click(element) {
  await act(async () => {
    await user.click(element)
  })
}

async function type(element, value) {
  await act(async () => {
    await user.type(element, value)
  })
}

async function fillAuthForm({ email, nickname, password }) {
  await type(screen.getByPlaceholderText('email'), email)
  if (nickname) {
    await type(screen.getByPlaceholderText('nickname (2-24 chars)'), nickname)
  }
  await type(screen.getByPlaceholderText('password (8+ chars)'), password)
}

describe('App auth screen', () => {
  it('shows the backend error when a signup is rejected', async () => {
    routeFetch([
      {
        match: '/api/auth/refresh',
        method: 'POST',
        respond: () => jsonResponse({ detail: 'Invalid refresh token' }, { status: 401 }),
      },
      {
        match: '/api/auth/signup',
        method: 'POST',
        respond: () =>
          jsonResponse({ detail: 'Email already registered' }, { status: 400 }),
      },
    ])
    render(<App />)

    // the app asks the server whether the cookie holds a session first
    await screen.findByRole('button', { name: 'Need an account? Sign up' })
    await click(screen.getByRole('button', { name: 'Need an account? Sign up' }))
    await fillAuthForm({
      email: 'taken@example.com',
      nickname: 'alice',
      password: 'password123',
    })
    await click(screen.getByRole('button', { name: 'Sign up' }))

    const message = await screen.findByText('Email already registered')
    expect(message).toHaveClass('error')
    // the user stays on the auth screen and is not logged in
    expect(screen.queryByTestId('user-status')).not.toBeInTheDocument()
  })

  it('shows the backend error when a login is rejected', async () => {
    routeFetch([
      {
        match: '/api/auth/refresh',
        method: 'POST',
        respond: () => jsonResponse({ detail: 'Invalid refresh token' }, { status: 401 }),
      },
      {
        match: '/api/auth/login',
        method: 'POST',
        respond: () =>
          jsonResponse(
            { detail: 'Incorrect email or password' },
            { status: 401 },
          ),
      },
    ])
    render(<App />)

    await screen.findByPlaceholderText('email')
    await fillAuthForm({
      email: 'alice@example.com',
      password: 'wrongpassword',
    })
    await click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByText('Incorrect email or password')).toHaveClass(
      'error',
    )
  })

  it('keeps the session out of localStorage after a signup', async () => {
    routeFetch([
      {
        match: '/api/auth/refresh',
        method: 'POST',
        respond: () => jsonResponse({ detail: 'Invalid refresh token' }, { status: 401 }),
      },
      {
        match: '/api/auth/signup',
        method: 'POST',
        respond: () =>
          jsonResponse({ access_token: 'access-1', csrf_token: 'csrf-1' }),
      },
      {
        match: '/api/auth/me',
        respond: () => jsonResponse({ id: 1, nickname: 'alice' }),
      },
      { match: '/api/leagues', method: 'GET', respond: () => jsonResponse([]) },
    ])
    render(<App />)

    // the app asks the server whether the cookie holds a session first
    await screen.findByRole('button', { name: 'Need an account? Sign up' })
    await click(screen.getByRole('button', { name: 'Need an account? Sign up' }))
    await fillAuthForm({
      email: 'alice@example.com',
      nickname: 'alice',
      password: 'password123',
    })
    await click(screen.getByRole('button', { name: 'Sign up' }))

    expect(await screen.findByTestId('user-status')).toHaveTextContent(
      'Logged in as alice',
    )
    // nothing a script could steal is left on disk
    expect(localStorage.length).toBe(0)
  })

  it('restores the session from the cookie on load', async () => {
    const calls = []
    routeFetch([
      {
        match: '/api/auth/refresh',
        method: 'POST',
        respond: (url, init) => {
          calls.push({ url, init })
          return jsonResponse({ access_token: 'access-1', csrf_token: 'csrf-1' })
        },
      },
      {
        match: '/api/auth/me',
        respond: () => jsonResponse({ id: 1, nickname: 'alice' }),
      },
      { match: '/api/leagues', method: 'GET', respond: () => jsonResponse([]) },
    ])
    render(<App />)

    expect(await screen.findByTestId('user-status')).toHaveTextContent(
      'Logged in as alice',
    )
    // the cookie has to be sent, or the server cannot find the session
    expect(calls[0].init.credentials).toBe('include')
    // and the old token in localStorage is thrown away
    expect(localStorage.getItem('frager_token')).toBeNull()
    expect(localStorage.getItem('frager_refresh')).toBeNull()
  })
})
