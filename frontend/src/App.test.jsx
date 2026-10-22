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
        match: '/api/auth/signup',
        method: 'POST',
        respond: () =>
          jsonResponse({ detail: 'Email already registered' }, { status: 400 }),
      },
    ])
    render(<App />)

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

    await fillAuthForm({
      email: 'alice@example.com',
      password: 'wrongpassword',
    })
    await click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByText('Incorrect email or password')).toHaveClass(
      'error',
    )
  })

  it('stores the session and opens the leagues screen after a signup', async () => {
    routeFetch([
      {
        match: '/api/auth/signup',
        method: 'POST',
        respond: () =>
          jsonResponse({ access_token: 'access-1', refresh_token: 'refresh-1' }),
      },
      {
        match: '/api/auth/me',
        respond: () => jsonResponse({ id: 1, nickname: 'alice' }),
      },
      { match: '/api/leagues', respond: () => jsonResponse([]) },
    ])
    render(<App />)

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
    expect(localStorage.getItem('frager_token')).toBe('access-1')
    expect(localStorage.getItem('frager_refresh')).toBe('refresh-1')
  })
})
