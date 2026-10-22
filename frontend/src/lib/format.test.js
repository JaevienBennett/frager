import { describe, expect, it } from 'vitest'

import { findMyPick, parseStake, pickErrorMessage } from './format'

describe('parseStake', () => {
  it('treats an empty value as zero', () => {
    expect(parseStake('')).toBe(0)
    expect(parseStake('   ')).toBe(0)
    expect(parseStake(null)).toBe(0)
    expect(parseStake(undefined)).toBe(0)
  })

  it('parses whole numbers', () => {
    expect(parseStake('5')).toBe(5)
    expect(parseStake('0')).toBe(0)
  })

  it('trims surrounding whitespace', () => {
    expect(parseStake(' 7 ')).toBe(7)
  })

  it('rejects a fractional number', () => {
    expect(() => parseStake('2.5')).toThrow(
      'Stake must be a whole number of points (0 or more).',
    )
  })

  it('rejects junk', () => {
    expect(() => parseStake('abc')).toThrow(
      'Stake must be a whole number of points (0 or more).',
    )
    expect(() => parseStake('-3')).toThrow()
    expect(() => parseStake('1e3')).toThrow()
  })

  it('clamps values above the maximum instead of sending them to the API', () => {
    // The backend rejects a stake above 1000000 with a 422, so the client
    // clamps to the limit rather than sending an invalid value.
    expect(parseStake('1000000')).toBe(1000000)
    expect(parseStake('1000001')).toBe(1000000)
    expect(parseStake('99999999')).toBe(1000000)
  })
})

describe('pickErrorMessage', () => {
  it('explains a resolved prediction without repeating the raw reason', () => {
    const err = new Error('Prediction already resolved')
    err.status = 409
    expect(pickErrorMessage(err)).toBe(
      "This prediction was already resolved — your pick wasn't saved.",
    )
  })

  it('wraps other errors and adds the missing full stop', () => {
    expect(pickErrorMessage(new Error('Server exploded'))).toBe(
      'Your pick was NOT saved: Server exploded. Please try again.',
    )
  })

  it('keeps a reason that already ends in punctuation', () => {
    expect(pickErrorMessage(new Error('Server exploded.'))).toBe(
      'Your pick was NOT saved: Server exploded. Please try again.',
    )
  })
})

describe('findMyPick', () => {
  const detail = {
    picks_visible: true,
    picks: [
      { id: 1, user_id: 7, side: 'yes', stake: 10 },
      { id: 2, user_id: 9, side: 'no', stake: 20 },
    ],
  }

  it('returns null without a detail', () => {
    expect(findMyPick(null, 7)).toBeNull()
    expect(findMyPick(undefined, 7)).toBeNull()
  })

  it('returns null when picks are hidden', () => {
    expect(findMyPick({ ...detail, picks_visible: false }, 7)).toBeNull()
  })

  it('returns the pick belonging to the user', () => {
    expect(findMyPick(detail, 9)).toEqual({
      id: 2,
      user_id: 9,
      side: 'no',
      stake: 20,
    })
  })

  it('returns null when the user has not picked', () => {
    expect(findMyPick(detail, 99)).toBeNull()
  })
})
