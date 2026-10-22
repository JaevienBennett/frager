# Frager — working notes for Claude Code

Social prediction game (wager without risk): yes/no predictions, optional points, live
leaderboard. React/Vite frontend → FastAPI backend → PostgreSQL (Neon). Deployed on
Vercel (frontend) + Render (backend) + Neon (database).

Read `SPEC.md`, `README.md`, `AUDIT_REPORT.md` and `DEPLOY.md` before changing anything.
This file is the short version: the rules that are easy to break by accident.

## Hard rules (do not break these)

- **Never expose emails to other users.** Nicknames only. `UserOut` for `/api/auth/me`
  may include the caller's own email; nothing else may.
- **The leaderboard is derived, never stored.** It is computed from settled picks on
  every read. Never add a mutable points column.
- **Scoring:** a pick on the winning side earns `+stake`, a pick on the losing side
  earns `-stake`, stake `0` moves nothing but still counts for accuracy.
- **Only the prediction's creator may resolve it**, and only once. A second resolve is
  `409`.
- **Picks stay gated** until the caller has picked on that prediction or it is resolved.
  The detail endpoint returns `picks: []` and `picks_visible: false` otherwise.
- **bcrypt is pinned to `4.0.1`** (`backend/requirements.txt`). passlib breaks against
  newer bcrypt; do not bump it.
- **`backend/.env` is never committed.** It holds the production Neon `DATABASE_URL`
  with a password. Settings deny reading it.
- **No schema change without an idempotent migration** in `backend/migrations/migrate_v*.py`
  (nullable → backfill → NOT NULL; safe to run twice; PostgreSQL-specific). Discover FK
  constraint names dynamically via `pg_constraint`; do not hardcode them.
- **Never run a migration against Neon/production without explicit approval.** Verify
  against a scratch PostgreSQL first.
- **Deploy order:** backend before frontend whenever the frontend depends on a new
  endpoint, or the frontend breaks until the backend lands.
- **Do not `git checkout` / `switch` / `branch` / `worktree` / `commit` / `push`** unless
  explicitly asked. This checkout is shared with another agent working in the same tree.
- **Do not start long-running servers.**
- **Nothing that signs a user in may live in `localStorage`.** The refresh token is in an
  `httpOnly` cookie (`frager_refresh`, `Path=/api/auth`, `SameSite=None; Secure` over
  https), the access token and the CSRF token are in module state in
  `frontend/src/lib/api.js`. `logout` and `logout-all` need the `X-CSRF-Token` header
  when the cookie travels; `refresh` must stay CSRF-exempt (the app restores the session
  after a reload). The origin check uses the same `CORS_ORIGINS` list as the CORS
  middleware — one wrong entry there and every login is a 403.

## Traps specific to this codebase

- **Sync endpoints have no event loop.** FastAPI runs `def` endpoints in a worker thread,
  so `asyncio.create_task` there raises `RuntimeError` and the update is silently dropped.
  Use `ws.broadcast_nowait(...)` (`backend/app/ws.py`), which hands the broadcast back to
  the loop captured in the lifespan hook in `backend/app/main.py`. This was a real bug
  (M22) — every live update was dead until it was fixed.
- **Never key a rate limit on `request.client.host`.** Behind Render, uvicorn rewrites
  it from the *first* `X-Forwarded-For` entry, which the caller writes, so every limit
  was bypassable. Use `user_key()` (JWT subject) and `client_ip()`
  (`backend/app/rate_limit.py`) — and note that `client_ip()` reads the *last*
  `X-Forwarded-For` entry, not the first.
- **Do not rate-limit login on a request count.** Counting *every* attempt locks a
  legitimate user out — of their account, or of their whole address (a shared office IP).
  `rate_limit.note_failed_attempt(request, email, kind)` counts only *failures*, against
  a per-account budget (10 login / 5 signup a minute) **and** a per-address budget, so a
  correct password is never refused while one machine still cannot try a hundred
  accounts. `account_key()` and `stash_account_email()` were removed in M25 — do not
  reintroduce them.
- **slowapi details:** a per-limit `key_func` receives the request only if the endpoint
  parameter is literally named `request`; FastAPI resolves dependencies before the limit
  check, so `request.state.email` is available by then.
- **FastAPI wraps included routers** — `_IncludedRouter` — so the OpenAPI schema is the
  authoritative list of routes, not `app.routes`.
- **`frontend/src/App.jsx` is one large file** with `Leagues` and `LeagueView` in it. The
  HTTP/session helpers live in `frontend/src/lib/api.js` and the pure helpers in
  `frontend/src/lib/format.js`. Move code out only when it must move, and move it
  verbatim.
- **The session cookie is cross-site** (Vercel → Render), so it must be `SameSite=None`
  and `Secure` in production; `SameSite=Lax` over plain http (localhost, the test
  client). Every frontend request needs `credentials: 'include'` or the cookie never
  travels.
- **The frontend bundle is content-hashed**; the same source produces the same filename.
  A changed hash after a refactor means behaviour changed. Compare against the previous
  build to prove a refactor was a no-op.

## Commands

```bash
# backend tests (142) - needs a scratch PostgreSQL, never production
cd backend && DATABASE_URL='postgresql+psycopg2://postgres@localhost:55432/frager' python3 -m pytest tests -q

# frontend tests (53) and build
cd frontend && npm test
cd frontend && npm run build

# the backend imports cleanly
cd backend && python3 -c "import app.main"
```

## Where things live

| Path | What |
| --- | --- |
| `backend/app/main.py` | app, lifespan (captures the WS loop), `/api/health`, `/ws/leagues/{id}`, 429 handler, security headers |
| `backend/app/routes_auth.py` | signup, login, refresh, logout, logout-all, `/me` |
| `backend/app/routes_leagues.py` | leagues, invite links, join/leave, members, ownership transfer |
| `backend/app/routes_predictions.py` | predictions, picks, resolve, leaderboard, WS broadcasts |
| `backend/app/ws.py` | `ConnectionManager`, `broadcast_nowait()`, `set_event_loop()` |
| `backend/app/rate_limit.py` | `client_ip()`, `user_key()`, `failed_attempt_key()`, `note_failed_attempt()` |
| `backend/app/models.py` | `User`, `League`, `Membership`, `Prediction`, `Pick`, `RefreshToken` |
| `backend/app/schemas.py` | request/response models and their validation |
| `backend/app/membership.py` | `is_member()` |
| `backend/app/session_cookie.py` | the refresh cookie, the CSRF token, the origin check |
| `backend/tests/` | pytest suites (`conftest.py` seeds the DB and resets the limiter) |
| `frontend/src/App.jsx` | the whole UI: `App`, `Leagues`, `LeagueView` |
| `frontend/src/lib/` | `api.js` (fetch/session), `format.js` (pure helpers) |
| `frontend/src/test/` | Vitest setup: global fetch mock, fake WebSocket |
| `PROMPTS.md` | the milestone-prompt format used to hand work to another agent |
| `DEPLOY.md` | deploy order, Neon/Render/Vercel setup, proxy + rate-limit notes |

## How this project is worked on

A milestone prompt goes out → another agent implements it in this same tree → the result
is verified (tests, build, mutation checks, and where it matters a probe against the
live service) → a human reviews the diff → only then is it pushed. Verification is not
optional: M21–M23 were each found by reproducing the bug before fixing it.
