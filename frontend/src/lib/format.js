// Formatting helpers, moved verbatim out of App.jsx so they can be unit
// tested. Behaviour is unchanged: same names, same code.

export function parseStake(raw) {
  const trimmed = String(raw ?? '').trim()
  if (trimmed === '') return 0
  if (!/^\d+$/.test(trimmed)) {
    throw new Error('Stake must be a whole number of points (0 or more).')
  }
  return Math.min(Number(trimmed), 1000000)
}

export function pickErrorMessage(err) {
  if (err.status === 409) {
    return "This prediction was already resolved — your pick wasn't saved."
  }
  const reason = err.message
  return `Your pick was NOT saved: ${reason}${/[.!?]$/.test(reason) ? '' : '.'} Please try again.`
}

export function findMyPick(detail, userId) {
  if (!detail || !detail.picks_visible) return null
  return detail.picks.find((pk) => pk.user_id === userId) || null
}
