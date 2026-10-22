import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Leagues, LeagueView } from './App'
import { deliver, jsonResponse, lastSocket, routeFetch } from './test/helpers'

const OWNER = { id: 1, nickname: 'alice' }
const MEMBER = { id: 2, nickname: 'bob' }

const league = {
  id: 7,
  name: 'Friday Night League',
  invite_code: 'invite-abc',
  owner_id: OWNER.id,
  member_count: 2,
}

const leaderboard = [
  { user_id: 1, nickname: 'alice', points: 10, correct: 2, total: 3, accuracy: 0.67 },
  { user_id: 2, nickname: 'bob', points: 4, correct: 1, total: 3, accuracy: 0.33 },
]

const members = [
  { user_id: 1, nickname: 'alice', is_owner: true },
  { user_id: 2, nickname: 'bob', is_owner: false },
]

// Most specific first: "/api/leagues" is a prefix of every other league route.
// The catch-all is GET-only, so an unmocked POST (a pick, a resolve, ...)
// fails loudly instead of being answered with a league list.
function leagueRoutes(extra = []) {
  return [
    { match: '/api/leagues/7/predictions', respond: () => jsonResponse([]) },
    { match: '/api/leagues/7/leaderboard', respond: () => jsonResponse(leaderboard) },
    { match: '/api/leagues/7/members', respond: () => jsonResponse(members) },
    ...extra,
    { match: '/api/leagues', method: 'GET', respond: () => jsonResponse([league]) },
  ]
}

let user

beforeEach(() => {
  routeFetch(leagueRoutes())
  user = userEvent.setup()
})

// Clicks await fetches inside the handler, so the act() scope has to stay
// open until those promises settle.
async function click(element) {
  await act(async () => {
    await user.click(element)
  })
}

// Flush any state update that a fire-and-forget request triggers.
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

async function renderLeagueView(props = {}) {
  const view = render(
    <LeagueView
      token="test-token"
      userId={OWNER.id}
      league={league}
      onBack={vi.fn()}
      onUpdated={vi.fn()}
      onDeleted={vi.fn()}
      onLeft={vi.fn()}
      {...props}
    />,
  )
  await screen.findByTestId('leaderboard')
  await settle()
  return view
}

describe('LeagueView ownership controls', () => {
  it('shows the transfer button to the owner', async () => {
    await renderLeagueView()
    expect(screen.getByTestId('transfer-league')).toBeInTheDocument()
  })

  it('hides the transfer button from a non-owner', async () => {
    await renderLeagueView({ userId: MEMBER.id })
    expect(screen.queryByTestId('transfer-league')).not.toBeInTheDocument()
    expect(screen.getByTestId('leave-league')).toBeInTheDocument()
  })
})

describe('LeagueView transfer modal', () => {
  it('opens the modal and lists the members the backend returned', async () => {
    await renderLeagueView()

    await click(screen.getByTestId('transfer-league'))

    const modal = await screen.findByTestId('transfer-modal')
    expect(modal).toBeInTheDocument()
    expect(await within(modal).findByText('alice')).toBeInTheDocument()
    expect(within(modal).getByText('bob')).toBeInTheDocument()
    expect(within(modal).getByTestId('transfer-option-1')).toBeInTheDocument()
    expect(within(modal).getByTestId('transfer-option-2')).toBeInTheDocument()
  })

  it('cannot confirm until a member is selected', async () => {
    await renderLeagueView()

    await click(screen.getByTestId('transfer-league'))
    await screen.findByTestId('transfer-option-2')
    expect(screen.getByTestId('confirm-transfer')).toBeDisabled()

    await click(screen.getByTestId('transfer-option-2'))
    expect(screen.getByTestId('confirm-transfer')).toBeEnabled()
  })

  it('posts the selected member as the new owner', async () => {
    const posts = []
    routeFetch(
      leagueRoutes([
        {
          match: '/api/leagues/7/transfer',
          method: 'POST',
          respond: (url, init) => {
            posts.push({ url, body: JSON.parse(init.body) })
            return jsonResponse({ ...league, owner_id: MEMBER.id })
          },
        },
      ]),
    )
    await renderLeagueView()

    await click(screen.getByTestId('transfer-league'))
    await screen.findByTestId('transfer-option-2')
    await click(screen.getByTestId('transfer-option-2'))
    await click(screen.getByTestId('confirm-transfer'))

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain('/api/leagues/7/transfer')
    expect(posts[0].body).toEqual({ new_owner_id: MEMBER.id })
  })

  it('shows the backend error in the modal instead of swallowing it', async () => {
    routeFetch(
      leagueRoutes([
        {
          match: '/api/leagues/7/transfer',
          method: 'POST',
          respond: () =>
            jsonResponse(
              { detail: 'Only the league owner can transfer ownership' },
              { status: 403 },
            ),
        },
      ]),
    )
    await renderLeagueView()

    await click(screen.getByTestId('transfer-league'))
    await screen.findByTestId('transfer-option-2')
    await click(screen.getByTestId('transfer-option-2'))
    await click(screen.getByTestId('confirm-transfer'))

    expect(
      await screen.findByText('Only the league owner can transfer ownership'),
    ).toBeInTheDocument()
    // the modal stays open so the user can pick someone else
    expect(screen.getByTestId('transfer-modal')).toBeInTheDocument()
  })
})

describe('LeagueView void predictions', () => {
  const voidPrediction = {
    id: 11,
    question: 'Will it rain tomorrow?',
    status: 'void',
    creator_id: null,
    created_at: '2026-01-01T00:00:00Z',
    yes_count: 2,
    no_count: 1,
    yes_stake: 10,
    no_stake: 5,
    resolved_outcome: null,
  }

  function voidRoutes() {
    return [
      {
        match: '/api/leagues/7/predictions',
        respond: () => jsonResponse([voidPrediction]),
      },
      {
        match: '/api/predictions/11',
        respond: () =>
          jsonResponse({ ...voidPrediction, picks: [], picks_visible: true }),
      },
      { match: '/api/leagues/7/leaderboard', respond: () => jsonResponse(leaderboard) },
      { match: '/api/leagues/7/members', respond: () => jsonResponse(members) },
      { match: '/api/leagues', method: 'GET', respond: () => jsonResponse([league]) },
    ]
  }

  it('marks a void prediction and offers no resolve buttons', async () => {
    routeFetch(voidRoutes())
    await renderLeagueView()

    const item = await screen.findByTestId('prediction-item')
    expect(item).toHaveTextContent('(void)')
    expect(item.querySelector('.badge')).toHaveClass('badge-void')
    expect(screen.getByTestId('void-banner')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resolve Yes' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resolve No' })).not.toBeInTheDocument()
    // a void prediction is not open, so it cannot be picked on either
    expect(screen.queryByRole('button', { name: 'Pick' })).not.toBeInTheDocument()
  })

  it('does not crash on a prediction whose creator deleted the account', async () => {
    routeFetch(
      voidRoutes().map((r) =>
        r.match === '/api/leagues/7/predictions'
          ? { ...r, respond: () => jsonResponse([{ ...voidPrediction, status: 'open' }]) }
          : r,
      ),
    )
    await renderLeagueView()

    const item = await screen.findByTestId('prediction-item')
    expect(item).toHaveTextContent('(open)')
    // nobody owns it any more, so nobody may resolve it
    expect(screen.queryByRole('button', { name: 'Resolve Yes' })).not.toBeInTheDocument()
  })
})

describe('LeagueView owner badge', () => {
  it('marks the owner in the leaderboard and nobody else', async () => {
    await renderLeagueView()

    const badges = screen.getAllByTestId('owner-badge')
    expect(badges).toHaveLength(1)
    expect(badges[0].parentElement).toHaveTextContent('alice')
    expect(badges[0].parentElement).not.toHaveTextContent('bob')
  })

  it('moves the badge when the server reports a new owner', async () => {
    routeFetch(leagueRoutes())
    render(<Leagues token="test-token" userId={OWNER.id} />)

    await click(await screen.findByText('Friday Night League'))
    await screen.findByTestId('leaderboard')
    await settle()

    expect(screen.getByTestId('owner-badge').parentElement).toHaveTextContent(
      'alice',
    )

    const socket = lastSocket()
    expect(socket).toBeDefined()
    act(() => {
      deliver(socket, { type: 'league_updated', owner_id: MEMBER.id })
    })
    await settle()

    await waitFor(() =>
      expect(screen.getByTestId('owner-badge').parentElement).toHaveTextContent(
        'bob',
      ),
    )
    expect(screen.getAllByTestId('owner-badge')).toHaveLength(1)
  })
})
