import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App, { Account } from './App'
import { jsonResponse, routeFetch } from './test/helpers'

const USER = { id: 1, nickname: 'alice' }

const OWNED_SHARED = {
  id: 7,
  name: 'Friday Night League',
  invite_code: 'invite-abc',
  owner_id: USER.id,
  member_count: 2,
}
const OWNED_SOLE = {
  id: 8,
  name: 'Solo League',
  invite_code: 'invite-def',
  owner_id: USER.id,
  member_count: 1,
}
const NOT_OWNED = {
  id: 9,
  name: 'Other League',
  invite_code: 'invite-ghi',
  owner_id: 2,
  member_count: 3,
}

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

function accountRoutes(extra = [], leagues = []) {
  return [
    { match: '/api/leagues', method: 'GET', respond: () => jsonResponse(leagues) },
    ...extra,
  ]
}

async function renderAccount(props = {}) {
  const onPasswordChanged = props.onPasswordChanged || vi.fn()
  const onDeleted = props.onDeleted || vi.fn()
  render(
    <Account
      token="test-token"
      user={USER}
      onPasswordChanged={onPasswordChanged}
      onDeleted={onDeleted}
      {...props}
    />,
  )
  await waitFor(() => expect(onPasswordChanged).toBeDefined())
  return { onPasswordChanged, onDeleted }
}

describe('Account delete-account guard', () => {
  it('lists the leagues that still have other members and blocks the button', async () => {
    routeFetch(accountRoutes([], [OWNED_SHARED, OWNED_SOLE, NOT_OWNED]))
    await renderAccount()

    const blocking = await screen.findByTestId('blocking-leagues')
    expect(blocking).toHaveTextContent('Friday Night League')
    expect(blocking).not.toHaveTextContent('Solo League')
    expect(blocking).not.toHaveTextContent('Other League')

    expect(screen.getByTestId('deleted-leagues')).toHaveTextContent('Solo League')
    expect(screen.getByTestId('delete-account')).toBeDisabled()
  })

  it('does not list leagues the user does not own', async () => {
    routeFetch(accountRoutes([], [NOT_OWNED]))
    await renderAccount()

    await waitFor(() =>
      expect(screen.getByTestId('delete-account')).toBeEnabled(),
    )
    expect(screen.queryByTestId('blocking-leagues')).not.toBeInTheDocument()
  })
})

describe('Account change password', () => {
  it('posts the new password and hands the new session back', async () => {
    const posts = []
    routeFetch(
      accountRoutes([
        {
          match: '/api/auth/change-password',
          method: 'POST',
          respond: (url, init) => {
            posts.push({ url, body: JSON.parse(init.body) })
            return jsonResponse({
              access_token: 'access-2',
              csrf_token: 'csrf-2',
            })
          },
        },
      ]),
    )
    const { onPasswordChanged } = await renderAccount()

    await type(screen.getByTestId('current-password'), 'oldpassword')
    await type(screen.getByTestId('new-password'), 'newpassword')
    await type(screen.getByTestId('confirm-password'), 'newpassword')
    await click(screen.getByRole('button', { name: 'Change password' }))

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain('/api/auth/change-password')
    expect(posts[0].body).toEqual({
      current_password: 'oldpassword',
      new_password: 'newpassword',
    })
    expect(onPasswordChanged).toHaveBeenCalledWith({
      access_token: 'access-2',
      csrf_token: 'csrf-2',
    })
    expect(await screen.findByTestId('password-done')).toBeInTheDocument()
  })

  it('shows the backend error when the current password is wrong', async () => {
    routeFetch(
      accountRoutes([
        {
          match: '/api/auth/change-password',
          method: 'POST',
          respond: () =>
            jsonResponse(
              { detail: 'Current password is incorrect' },
              { status: 400 },
            ),
        },
      ]),
    )
    await renderAccount()

    await type(screen.getByTestId('current-password'), 'wrongpassword')
    await type(screen.getByTestId('new-password'), 'newpassword')
    await type(screen.getByTestId('confirm-password'), 'newpassword')
    await click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByTestId('password-error')).toHaveTextContent(
      'Current password is incorrect',
    )
  })

  it('refuses two different new passwords without calling the backend', async () => {
    const posts = []
    routeFetch(
      accountRoutes([
        {
          match: '/api/auth/change-password',
          method: 'POST',
          respond: () => {
            posts.push(1)
            return jsonResponse({})
          },
        },
      ]),
    )
    await renderAccount()

    await type(screen.getByTestId('current-password'), 'oldpassword')
    await type(screen.getByTestId('new-password'), 'newpassword')
    await type(screen.getByTestId('confirm-password'), 'different')
    await click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByTestId('password-error')).toHaveTextContent(
      'not the same',
    )
    expect(posts).toHaveLength(0)
  })
})

describe('Account delete account', () => {
  it('refuses to delete until the nickname is typed', async () => {
    const posts = []
    routeFetch(
      accountRoutes([
        {
          match: '/api/auth/delete-account',
          method: 'POST',
          respond: () => {
            posts.push(1)
            return jsonResponse({ ok: true })
          },
        },
      ]),
    )
    const { onDeleted } = await renderAccount()

    await type(screen.getByTestId('delete-password'), 'password123')
    await type(screen.getByTestId('delete-confirm'), 'bob')
    await click(screen.getByTestId('delete-account'))

    expect(await screen.findByTestId('delete-error')).toHaveTextContent(
      'Type "alice" to confirm.',
    )
    expect(posts).toHaveLength(0)
    expect(onDeleted).not.toHaveBeenCalled()
  })

  it('deletes the account and tells the app to sign out', async () => {
    const posts = []
    routeFetch(
      accountRoutes([
        {
          match: '/api/auth/delete-account',
          method: 'POST',
          respond: (url, init) => {
            posts.push({ url, body: JSON.parse(init.body) })
            return jsonResponse({ ok: true })
          },
        },
      ]),
    )
    const { onDeleted } = await renderAccount()

    await type(screen.getByTestId('delete-password'), 'password123')
    await type(screen.getByTestId('delete-confirm'), 'alice')
    await click(screen.getByTestId('delete-account'))

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain('/api/auth/delete-account')
    expect(posts[0].body).toEqual({ password: 'password123' })
    expect(onDeleted).toHaveBeenCalled()
  })

  it('shows the 409 when a league still has other members', async () => {
    routeFetch(
      accountRoutes([
        {
          match: '/api/auth/delete-account',
          method: 'POST',
          respond: () =>
            jsonResponse(
              {
                detail:
                  'Transfer or delete the leagues you own that have other members first',
              },
              { status: 409 },
            ),
        },
      ]),
    )
    const { onDeleted } = await renderAccount()

    await type(screen.getByTestId('delete-password'), 'password123')
    await type(screen.getByTestId('delete-confirm'), 'alice')
    await click(screen.getByTestId('delete-account'))

    expect(await screen.findByTestId('delete-error')).toHaveTextContent(
      'Transfer or delete the leagues you own',
    )
    expect(onDeleted).not.toHaveBeenCalled()
  })
})

describe('App account view', () => {
  it('signs the user out after the account is deleted', async () => {
    routeFetch([
      {
        match: '/api/auth/refresh',
        method: 'POST',
        respond: () =>
          jsonResponse({ access_token: 'access-1', csrf_token: 'csrf-1' }),
      },
      {
        match: '/api/auth/me',
        respond: () => jsonResponse({ id: USER.id, nickname: USER.nickname }),
      },
      { match: '/api/leagues', method: 'GET', respond: () => jsonResponse([]) },
      {
        match: '/api/auth/delete-account',
        method: 'POST',
        respond: () => jsonResponse({ ok: true }),
      },
    ])
    render(<App />)

    await screen.findByTestId('user-status')
    await click(screen.getByTestId('account-button'))

    await type(screen.getByTestId('delete-password'), 'password123')
    await type(screen.getByTestId('delete-confirm'), 'alice')
    await click(screen.getByTestId('delete-account'))

    await waitFor(() =>
      expect(screen.queryByTestId('user-status')).not.toBeInTheDocument(),
    )
    expect(localStorage.getItem('frager_token')).toBeNull()
    expect(localStorage.getItem('frager_refresh')).toBeNull()
    expect(localStorage.length).toBe(0)
  })
})
