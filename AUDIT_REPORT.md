# Frager Audit Report (M0–M14)

Date: 2026-10-20 (audit) · updated 2026-10-21 (after M15–M19 fixes) · 2026-10-21 (after M20–M23 fixes)
Repo: /Users/og.jae/projects/frager (main)
Stack: FastAPI + SQLAlchemy + PostgreSQL (Neon), React + Vite, JWT auth (bcrypt pinned), Render/Vercel

> Status legend: **FIXED (M##)** = addressed in a later milestone, see [Implemented Fixes](#implemented-fixes).
> The findings below are kept as the original audit record, with resolution notes added.

## 1) WebSockets / Real-time — FIXED (M16, broadcast fixed M22)
- **Spec says:** "Real-time: WebSockets (FastAPI)", v1 includes "Leaderboard updates live (real-time)".
- **Current state:** No WebSocket endpoints, no WS client in frontend. All updates use REST + manual refetches (after pick/resolve/create). 
- **Evidence:** `backend/app/main.py` has no `websockets` imports/routers; `frontend/src/App.jsx` uses `fetchJson`/`fetchJsonWithRetry` only.
- **Recommendation (HIGH):** Add minimal WS for league/prediction updates (e.g. `/ws/leagues/{id}`) broadcasting on pick/resolve/create. Keep HTTP fallback. This is feasible with FastAPI + `websockets` (already a common dep) but adds complexity; if time-constrained, document as gap and add "refresh" UX.
- **Effort:** Med-High. **Risk:** Med (connection management, auth). **Fix suggested:** Implement lightweight pub/sub per league with token auth on connect; broadcast events on mutations. Add frontend WS client with reconnect + fallback to current refetches.
- **Resolution:** Implemented in M16 — `backend/app/ws.py` (per-league `ConnectionManager`),
  `GET /ws/leagues/{league_id}` in `backend/app/main.py` (JWT via `?token=`, membership
  required), events broadcast on create/pick/resolve, and a frontend WS client with
  exponential-backoff reconnect plus HTTP fallback.
- **Correction (M22):** the M16 broadcasts never reached anybody. Every endpoint that
  broadcasts is a `def` function, so FastAPI runs it in a worker thread; `asyncio.create_task`
  has no running event loop there and raised `RuntimeError`, which the `except Exception: pass`
  around it swallowed. Live updates had therefore never worked. Fixed in M22 by capturing the
  app's event loop at startup and handing the broadcast back to it.

## 2) API Robustness
- **Auth:** All protected routes use `get_current_user`. `routes_leagues`/`routes_predictions` enforce membership. **OK**.
- **Validation:** Pydantic schemas present; `PickCreate.stake >= 0`, `side` Literal, signup nickname 2-24. **OK**.
- **Errors:** 404 for missing/non-member, 403 for non-creator resolve, 409 for already-resolved/duplicate membership/pick-on-resolved. **OK** (note: `make_pick` returns 409 "Prediction is already settled" vs resolve returns "Prediction is already resolved" - slightly different messages, both 409).
- **CORS:** Configurable via `CORS_ORIGINS` (comma-split), defaults include localhost:5173. **OK**.
- **Evidence:** `backend/app/security.py`, `backend/app/routes_*.py`, `backend/app/main.py`.

## 3) Frontend UX
- **Loading/retry:** Mount GETs use `fetchJsonWithRetry` (3 attempts), waking-up states. Pick has retry only on network errors. **OK**.
- **Errors:** Pick errors inline, page errors shown. **OK**.
- **Empty states:** Added for leagues and predictions. **OK** (M12).
- **Mobile:** Responsive CSS, table scrolls. **OK**.
- **Validation:** Stake parsed strictly client-side; inline errors. **OK**.
- **A11y:** Segmented toggle has `role="group"` and `aria-pressed`. **OK**.
- **Gaps (MED):** No form validation for empty question beyond `required`; no debouncing; large lists unvirtualized (small scale fine). — **FIXED (M18):** client trims and validates the same 1–500 / 1–100 limits as the server (still no debouncing/unvirtualization, fine at this scale).

## 4) Picks
- **Update before resolve:** `make_pick` allows updating existing pick (200) if user already picked. **OK**.
- **Gating:** Server-side gating in `get_prediction` - picks hidden until caller picked OR resolved. **OK**.
- **Stake validation:** Schema `ge=0`, frontend clamps/validates. **OK**.
- **Max stake:** Frontend clamps to 1000000; backend has no explicit max (schema allows up to integer). **MED** - add backend max to prevent abuse. — **FIXED (M15):** `PickCreate.stake` is now `Field(ge=0, le=1000000)` (`app/schemas.py:74`), matching the frontend clamp.
- **Evidence:** `routes_predictions.py:90-129`, `schemas.py:71-84`.

## 5) Leaderboard
- **Derived:** Computed from settled picks each request. **OK**.
- **Sorting:** `entries.sort(key=lambda e: (-e.points, -e.accuracy, e.user_id))` - matches README (points desc, accuracy desc, user_id tie-break). **OK**.
- **Zero-pick members included:** Yes. **OK**.
- **Emails exposed:** LeaderboardEntry now uses `nickname` only. **OK**.
- **Evidence:** `routes_predictions.py:200-250`.

## 6) Leagues
- **Invite codes:** `secrets.token_urlsafe(6)`, stored unique. **OK**.
- **Join flow:** 404 unknown, 409 duplicate. Owner auto-member. **OK**.
- **Membership checks:** Used everywhere. **OK**.
- **Management:** No rename/delete/leave endpoints; no shareable invite link (v1 gap). — **FIXED (M19):** `PATCH`/`DELETE /api/leagues/{id}` (owner-only) and `POST /api/leagues/{id}/leave` (members; owner gets 409); frontend adds rename/delete/leave controls plus a `/?join=CODE` invite link. Deletes rely on the M18 cascades. — **FIXED (M21):** `POST /api/leagues/{id}/transfer` hands the league to another member, so an owner is no longer stuck (they stay a member and can then leave).

## 7) Auth
- **Tokens:** JWT (python-jose), bcrypt via passlib (pinned 4.0.1). **OK**.
- **Session:** localStorage token, /me on load. **OK**. — **FIXED (M26):** the refresh
  token is in an `httpOnly` cookie (`frager_refresh`, `Path=/api/auth`, `SameSite=None;
  Secure` over https), the access token is in memory only, and the app restores the
  session after a reload with `POST /api/auth/refresh` (no body).
- **Logout:** Clears token. **OK**.
- **Password requirements:** No explicit complexity beyond non-empty (schema just requires password). **LOW** - consider minimum length. — **FIXED (M17):** `Credentials.password` is `Field(min_length=8, max_length=128)`; frontend enforces `minLength={8}`.
- **Token expiry:** Configurable `ACCESS_TOKEN_EXPIRE_MINUTES`. — **IMPROVED (M20):** rotating opaque refresh tokens with per-user token versioning, logout-all invalidation, and theft detection.
- **CSRF:** the cookie-authenticated endpoints (`logout`, `logout-all`) need a CSRF token
  in the `X-CSRF-Token` header, and every mutating auth endpoint refuses a request whose
  `Origin` is not in `CORS_ORIGINS`. — **ADDED (M26).**
- **Evidence:** `app/security.py`, `app/routes_auth.py`, `app/config.py`,
  `app/session_cookie.py`.

## 8) Predictions
- **Creation:** Works with/without game link (M14). **OK**.
- **Question length:** No max in schema (model allows up to 500 chars). **OK**. — **FIXED (M18):** `PredictionCreate.question` trims and enforces 1–500; `LeagueCreate.name` 1–100.
- **Resolved state UI:** Banner + ticks/swing + auto-resolution. **OK**.
- **Only creator resolves:** Enforced. **OK**.

## 9) Migrations
- **Idempotent:** `migrate_v4.py`, `migrate_v7.py`, `migrations/migrate_v14_auto_resolve.py` all use IF NOT EXISTS / NULL checks / backfills. **OK**.
- **Order:** Backfill before constraints where needed. **OK**.
- **Run safely:** Confirmed v14 runs twice cleanly.

## 10) Tests — FIXED (M15)
- **Existing:** Only `backend/tests/test_m14_auto_resolve.py` (unittest-style functions, no pytest). **GAP (MED)** - add smoke tests for auth/leagues/predictions/picks/resolve/leaderboard. — **FIXED (M15):** added `backend/tests/test_smoke_flows.py` (health, signup/login/me, leagues, predictions, picks, resolve, leaderboard) using `TestClient`.
- **Coverage:** Core flows untested. **Recommendation:** Add basic integration tests using TestClient. — 10 tests pass via `python -m pytest backend/tests` (run from `backend/`).

## 11) Security
- **Secrets:** .env gitignored, .env.example provided. **OK**.
- **SQL injection:** SQLAlchemy ORM used throughout. **OK**.
- **Rate limiting:** None. **MED** for production (especially auth endpoints). — **FIXED (M17):** `slowapi` limiter; signup `5/minute`, login `10/minute`, 429 via `RateLimitExceeded` handler. — **FIXED (M23):** the M17 limiter keyed on `request.client.host`, which uvicorn rewrites from the *first* `X-Forwarded-For` entry — a header the caller writes. Behind Render (`FORWARDED_ALLOW_IPS=*`) that made every limit bypassable with a fresh header per request (proved in production: 13 different header values, no throttling). Limits now key on the account (email) and the signed-in user (JWT subject) first, and on the real client address second (`CF-Connecting-IP`, else the last `X-Forwarded-For` entry).
- **CORS:** Configurable. **OK**.
- **Headers:** No security headers middleware. **LOW**. — **FIXED (M17):** `nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 0`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`.
- **bcrypt pinned:** 4.0.1 in requirements. **OK**.

## 12) Deployment
- **Config:** `VITE_API_URL` env var, `CORS_ORIGINS` env var, Render start command documented. **OK**.
- **Files:** `backend/render.yaml`, `DEPLOY.md`, `.env.example` files present. **OK**.

## 13) Data Integrity
- **FKs:** Present. **OK**.
- **Cascades:** Not explicitly set (defaults). Usually fine if deletes handled carefully. **LOW**. — **FIXED (M18):** core FKs are `ON DELETE CASCADE` (models + `migrate_v18_cascades.py`); `passive_deletes=True` on the owning relationships.
- **Unique constraints:** `users.email`, `users.nickname`, `leagues.invite_code`, `memberships(league_id,user_id)`, `picks(prediction_id,user_id)`. **OK**.

## 14) Misc
- **README:** Generally accurate, mentions M14 features partially. **OK**.
- **Dead code/TODOs:** None obvious.
- **Frontend build:** Passes.
- **Backend imports:** Pass.

## High Priority Fixes (implement) — all DONE
1. **Add backend max stake validation** (schema + route) - prevent abuse, consistent with frontend clamp. — **DONE (M15)**
2. **Add basic smoke tests** for core flows (auth, leagues, create prediction/pick, resolve, leaderboard) using TestClient. — **DONE (M15)**
3. **Harden pick/update rules** - ensure stake validation on update too (already done via schema). — **OK (no change needed)**
4. **Add security headers middleware** (optional but good) - low risk. — **DONE (M17)**

## Medium Priority — all DONE
1. **WebSockets** - nice to have for "live leaderboard" per spec; can defer if complex, but worth minimal implementation. — **DONE (M16)**
2. **Rate limiting** on auth endpoints. — **DONE (M17)**
3. **Password minimum length**. — **DONE (M17)**

## Still open (not yet scheduled)
- WS connection manager is in-process (single-instance hosting assumed).
- No debouncing / list virtualization (fine at current scale).
- No frontend test infrastructure (the frontend is only covered by `npm run build`).
  **Fixed in M24**: Vitest + Testing Library, 35 tests over the helpers, the API error
  and 401-refresh path, the ownership-transfer UI and the websocket owner-badge update.
  `npm audit` still reports 5 dev-only advisories (esbuild/vite dev server, vite-node,
  tinypool); they are unreachable in the deployed app and fixing them needs a breaking
  Vitest 5 / Vite 8 upgrade.
- ~~No password-change endpoint and no account-deletion endpoint.~~ **Fixed in M25**:
  `POST /api/auth/change-password` and `POST /api/auth/delete-account` (the user's open
  predictions are voided, their picks removed, and the leagues they are the last member of
  are deleted).
- ~~Refresh tokens still live in `localStorage`.~~ **Fixed in M26**: the refresh token
  travels in an `httpOnly` cookie, the access token lives in memory only, and the old
  `localStorage` keys are deleted on startup. The cookie is cross-site
  (`SameSite=None; Secure`), so the endpoints that use it check the `Origin` header and
  require a CSRF token.
- Rate limit counters live in process memory, so a multi-instance deployment would count
  per instance (Render currently runs one).
- `users.id` → `leagues.owner_id` is `ON DELETE CASCADE`: deleting a user would delete the
  leagues they own. **M25**: `delete-account` refuses with 409 while the user still owns a
  league with other members — the league has to be transferred or deleted first.

## Implemented Fixes

### M15 — Audit & gap-fill
- `backend/app/schemas.py`: `PickCreate.stake` bounded to `0..1000000`.
- `backend/tests/test_smoke_flows.py`: new TestClient smoke suite (health, auth, leagues,
  predictions, picks, resolve, leaderboard).
- `AUDIT_REPORT.md`: this report.

### M16 — WebSockets / real-time
- `backend/app/ws.py`: `ConnectionManager` tracking sockets per league, with
  connect/disconnect/broadcast and cleanup of dead sockets.
- `backend/app/main.py`: `GET /ws/leagues/{league_id}` — JWT via `?token=`, membership
  required before accepting the socket.
- `backend/app/routes_predictions.py`: broadcasts `prediction_created`, `pick_updated`,
  `prediction_resolved`, `leaderboard_updated` after each commit.
- `frontend/src/App.jsx`: WS client in `LeagueView` with exponential-backoff reconnect
  (max 5s) and graceful HTTP fallback.
- `backend/requirements.txt`: added `websockets`.

### M17 — Auth hardening
- `backend/app/rate_limit.py`: slowapi limiter (remote address).
- `backend/app/main.py`: `app.state.limiter`, `RateLimitExceeded` -> 429 handler, and
  security-headers middleware.
- `backend/app/routes_auth.py`: signup `5/minute`, login `10/minute`.
- `backend/app/schemas.py`: password `min_length=8`, `max_length=128`.
- `frontend/src/App.jsx`: `minLength={8}` on the password field + "8+ chars" hint.
- `backend/requirements.txt`: added `slowapi`.

### M18 — Input validation + cascade integrity
- `backend/app/schemas.py`: `PredictionCreate.question` trims and enforces 1–500 chars;
  `LeagueCreate.name` trims and enforces 1–100 chars.
- `backend/app/models.py`: `ondelete="CASCADE"` on the seven core FKs; `passive_deletes=True`
  on the owning relationships so Postgres performs the delete.
- `backend/migrations/migrate_v18_cascades.py`: dynamic, idempotent migration that rewrites
  existing FKs to `ON DELETE CASCADE` (applied to Neon; second run changed 0/7).
- `backend/tests/test_m18_validation.py` + `backend/tests/conftest.py`: validation, schema
  limits, migration idempotency, and cascade-delete coverage.
- `frontend/src/App.jsx`: client-side trim + length validation and `maxLength` for league
  names and prediction questions.

### M19 — League management + invite links
- `backend/app/routes_leagues.py`: `PATCH /api/leagues/{id}` (rename, owner-only),
  `DELETE /api/leagues/{id}` (owner-only; cascades memberships/predictions/picks), and
  `POST /api/leagues/{id}/leave` (members; owner gets 409).
- `backend/app/schemas.py`: `LeagueUpdate` reuses a shared `normalize_league_name()` so
  create/rename validation cannot drift (trim, 1–100, non-blank).
- `backend/tests/test_m19_league_management.py`: 18 tests for permissions, validation,
  leave rules, and cascade deletion (including a non-vacuous cascade assertion).
- `frontend/src/App.jsx` + `styles.css`: owner rename/delete and member leave controls,
  shareable invite link with copy button, and `/?join=CODE` pre-fill.
- Docs: README API/features, DEPLOY migration prerequisite.

### M20 — Sessions: rotating refresh tokens + revocation
- `backend/app/models.py`: `User.token_version` + new `refresh_tokens` table (only SHA-256
  hashes stored, `user_id` `ON DELETE CASCADE`).
- `backend/app/security.py`: access tokens include `"ver"` claim; `get_current_user`
  rejects tokens whose version doesn't match; `hash_refresh_token()` added.
- `backend/app/routes_auth.py`: `POST /api/auth/refresh` rotates tokens (replay of a
  freshly rotated token within the grace window is treated as a race, not theft; replay
  much later revokes all sessions), `POST /api/auth/logout` (single token), and
  `POST /api/auth/logout-all` (version bump + revoke all).
- `backend/app/schemas.py`: `Token` now includes `refresh_token`; added `RefreshRequest`.
- `backend/migrations/migrate_v20_sessions.py`: idempotent migration for `users.token_version`,
  `refresh_tokens`, indexes, and the cascade FK; safe to run twice.
- `backend/tests/test_m20_sessions.py`: 16 tests covering rotation, theft detection,
  logout/logout-all, expiry, backward compat with legacy access tokens, and migration
  idempotency.
- `frontend/src/App.jsx`: stores access + refresh tokens, silently refreshes-and-retries on
  401, refreshes on boot, revokes on logout, and adds a "Log out all" action.

### M21 — League ownership transfer
- `backend/app/routes_leagues.py`: `GET /api/leagues/{id}/members` (member-gated list of
  `user_id`, `nickname`, `is_owner`; no emails) and `POST /api/leagues/{id}/transfer`
  (`{new_owner_id}`). Only the owner may transfer (403), the target must be a member (404),
  transferring to yourself is a 400, and the update is a conditional
  `UPDATE ... WHERE id = :id AND owner_id = :caller` so two racing owners cannot overwrite
  each other (409 "Ownership changed; reload and try again").
- The former owner stays a member and may then leave; the new owner inherits the
  "cannot leave an owned league" rule, whose message now points at transferring
  ("Owner cannot leave; transfer ownership or delete the league instead").
- `backend/app/schemas.py`: `LeagueMemberOut`, `TransferOwnership`.
- `backend/tests/test_m21_ownership_transfer.py`: 15 tests (member list, transfer, permissions,
  self-transfer, race guard, old owner may leave, new owner may not, league list refresh).
- `frontend/src/App.jsx` + `styles.css`: "Transfer ownership" button, member picker modal,
  an "Owner" badge in the leaderboard, and a `league_updated` websocket event so other
  members see the new owner.

### M22 — Websocket broadcasts that actually arrive
- `backend/app/ws.py`: `broadcast_nowait()` helper. It schedules the broadcast on the event
  loop captured at startup (`set_event_loop`), on the current loop when called from async
  code, and falls back to `anyio.from_thread.run` when no loop was captured. Each socket
  send has a 5 second timeout and dead sockets are dropped with a log line instead of
  `except Exception: pass`.
- `backend/app/main.py`: lifespan hook captures the running loop at startup and clears it
  on shutdown.
- `backend/app/routes_predictions.py`: the six `asyncio.create_task(ws.manager.broadcast(...))`
  call sites (which raised `RuntimeError: no running event loop` and were swallowed) now call
  `ws.broadcast_nowait(...)`.
- `backend/app/routes_leagues.py`: ownership transfers broadcast `league_updated`.
- `backend/tests/test_m22_ws_broadcast.py`: 6 tests — a pick and a prediction created over
  HTTP arrive on an open websocket, no "coroutine was never awaited" warning is raised, and
  strangers/bad tokens are still refused.

### M23 — Rate limits that cannot be walked around
- `backend/app/rate_limit.py`: rewritten. `client_ip()` returns the caller's address
  (`CF-Connecting-IP` — Cloudflare overwrites it — else the last `X-Forwarded-For` entry,
  else the socket address) and `user_key()` keys on the subject of the access token. The
  per-account key that M23 originally added was replaced in M25 by a **failure-only**
  budget (see below); `account_key()` and `stash_account_email()` no longer exist.
- `backend/app/routes_auth.py`: signup and login carry a per-account limit next to the
  per-address one, so credential stuffing against one account is capped at 10 attempts a
  minute no matter how many addresses or headers are used.
- `backend/app/routes_leagues.py` + `backend/app/routes_predictions.py`: per-user limits on
  create/join/rename/delete/leave/transfer and on create/pick/resolve.
- `backend/tests/test_m23_rate_limits.py`: 12 tests, including "rotating the forwarded
  header does not buy a new bucket" and "the account budget is not shared between accounts".
- `backend/tests/conftest.py`: an autouse fixture empties the in-memory limiter between
  tests, so one test cannot spend the budget of the next.

### M24 — Frontend test infrastructure (Vitest) + first UI tests
- `frontend/package.json`: Vitest + jsdom + Testing Library as **devDependencies only**;
  `npm test` (vitest run) and `npm run watch` scripts. `dependencies` untouched.
- `frontend/vite.config.js`: a `test` block (jsdom, globals, setup file) on the existing
  config — no second config file.
- `frontend/src/test/setup.js`: fetches are globally mocked and an unmatched call fails
  the test; a fake `WebSocket` lets a test push a server frame into the app.
- `frontend/src/lib/api.js` + `frontend/src/lib/format.js`: the HTTP/session helpers and
  `parseStake` / `pickErrorMessage` / `findMyPick` moved out of `App.jsx` **verbatim**
  and exported. `Leagues` and `LeagueView` are now exported for direct rendering.
- `frontend/src/lib/format.test.js` (13), `frontend/src/lib/api.test.js` (11),
  `frontend/src/LeagueView.test.jsx` (8), `frontend/src/App.test.jsx` (3).
- The production bundle is byte-identical to the pre-M24 build
  (`index-Bwraoy5S.js`, 166.77 kB / gzip 52.80 kB), which proves the refactor changed no
  behaviour.

### M25 — Account management + the M21–M24 review findings
**New endpoints**
- `backend/app/routes_auth.py`: `POST /api/auth/change-password` (current password +
  new password; bumps `token_version`, revokes every refresh token, closes the user's
  websockets, returns a new token pair) and `POST /api/auth/delete-account` (password only;
  the user row is locked `FOR UPDATE`, leagues the user owns that still have other members
  are refused with 409, the user's open predictions are voided, their picks are removed and
  the user is deleted).
- `backend/app/schemas.py`: `PasswordChange`, `AccountDelete`, and `PredictionOut.creator_id`
  is now `int | None`.
- `backend/app/models.py`: `Prediction.creator_id` is nullable with `ON DELETE SET NULL`, so
  a prediction survives the creator's account (other members' picks keep counting) and
  nobody owns it any more — nobody can resolve it.
- `backend/migrations/migrate_v25_creator_set_null.py`: idempotent, PostgreSQL-specific,
  discovers the foreign-key name through `pg_constraint`; prints what it changed and is
  safe to run twice.

**Review findings that were fixed**
- *MAJOR 1* — the rotated-`X-Forwarded-For` tests passed for the wrong reason: the
  assertions ran before the request was made. They now wait for the response and are
  wrapped in `ProxyHeadersMiddleware`, like uvicorn does in production.
- *MAJOR 2* — the per-account login limit counted **every** attempt, so ten successful
  logins locked a legitimate user out of their own account (a shared address, a mistyped
  password, a bot guessing one account). The limit now counts only *failures*:
  `rate_limit.note_failed_attempt(request, email, kind)` spends a budget of 10 login /
  5 signup failures a minute, a correct password always gets in, and an unknown email is
  charged exactly like a known one (no account-enumeration side channel). The same
  lockout existed one layer down — a request-count limit per address — and a production
  probe caught it: eleven wrong passwords from one address also refused the *correct*
  password that followed, because Render appends the real client address to
  `X-Forwarded-For` and every request from one machine shares that bucket. Login
  therefore has no request-count limit at all: the address is limited by failures too
  (10 a minute), which keeps the anti-stuffing strength — one machine cannot try a
  hundred accounts ten times each — without ever refusing a correct password.
- *MINOR 3* — a websocket that timed out or errored on send was left in the manager;
  `ws.py` now drops it.
- *MINOR 4* — leaving a league and transferring it at the same time could leave the league
  owned by somebody who is not a member. Both now take a row lock (`FOR UPDATE`) first.
- *MINOR 5* — the "broadcast from a plain thread does not raise" test could not fail (the
  helper swallows every error). It now asserts that the message reaches a connected client.
- *NIT 6* — the pick POST in the broadcast test was never asserted; it now checks `201`.
- *NIT 7* — a failed member load left the previous member list on screen; it is cleared.
- *NIT 8* — the catch-all route in the frontend tests answered unmocked POSTs with a league
  list; it is now GET-only, so an unmocked POST fails the test loudly.
- The websocket handshake now checks the token's `ver` claim against `user.token_version`
  and that the user still exists, and `close_user_nowait()` closes a user's sockets when
  the password changes or the account is deleted.

**Frontend**
- `frontend/src/App.jsx`: an **Account** view (change password; delete account with the
  nickname typed to confirm and the blocking leagues listed), a `void` badge and banner for
  voided predictions, and the stale-member-list fix.
- `frontend/src/Account.test.jsx` (9 tests) and two new cases in
  `frontend/src/LeagueView.test.jsx` (void badge, prediction without a creator).

### M26 — Session hardening: the refresh token leaves localStorage
**The problem.** The refresh token was in `localStorage`. Any script that runs on the page
— an XSS bug, a compromised dependency, a browser extension — could read it, and a
refresh token that can be read is a session that can be stolen for a month. It was in
`localStorage` because it has to survive a page reload.

**New module**
- `backend/app/session_cookie.py`:
  - `set_refresh_cookie(response, token)` / `clear_refresh_cookie(response)` — the cookie
    is `frager_refresh`, `HttpOnly`, `Path=/api/auth`, `Max-Age` = the refresh lifetime.
    Over https it is `Secure` + `SameSite=None` (the frontend is on Vercel and the API on
    Render, so the request is cross-site and `SameSite=Lax` would drop the cookie); over
    plain http (localhost, the test client) it is `SameSite=Lax` and not `Secure`.
  - `csrf_token(user_id, token_version)` — `HMAC-SHA256(SECRET_KEY, f"csrf:{user_id}:{token_version}")`,
    hex. Stable across tabs and across refresh-token rotations; dies when
    `token_version` moves (password change, log out all).
  - `require_csrf(request, expected)` — 403 `CSRF token missing or invalid`.
  - `require_allowed_origin(request)` — 403 `Origin not allowed` when the `Origin` header
    is present and is not in `CORS_ORIGINS`. A request without an `Origin` header is
    allowed (curl, the test client).
- `backend/app/config.py`: `CORS_ORIGINS` (moved out of `main.py`, same parsing — the
  CORS middleware and the origin check now read the same list) and `REFRESH_COOKIE_ONLY`
  (the rollout switch).
- `backend/app/routes_auth.py`: signup, login, refresh and change-password set the cookie
  and return `{access_token, csrf_token}`; refresh reads the cookie instead of the body;
  logout revokes the session the cookie points at and clears it; logout-all bumps
  `token_version`, revokes every session and clears it; delete-account clears it. The
  origin check runs on every mutating auth endpoint, and `logout`/`logout-all` require
  the CSRF token **when the cookie travels**. `refresh` stays CSRF-exempt: the app has to
  be able to restore a session after a reload, before it has a CSRF token.
- `backend/app/main.py`: every `/api/auth` response carries `Cache-Control: no-store`.
- `frontend/src/lib/api.js`: the access token, the CSRF token and "do we have a session"
  live in module state — never in `localStorage`. Every request sends
  `credentials: 'include'` so the cookie travels, and the CSRF token as the
  `X-CSRF-Token` header. The app boots with `POST /api/auth/refresh` (no body) and asks
  the server whether the cookie still holds a session; the old `frager_token` /
  `frager_refresh` keys are deleted on startup. A refresh that comes back as 401
  `Refresh token already rotated` (another tab rotated the cookie first) is retried once
  after 500 ms.
- `frontend/src/App.jsx`: `logout` and `logout-all` send no refresh token in the body any
  more; the boot effect restores the session from the cookie.

**The rollout** is three phases, because the two sides have to agree on the transition:
(a) the backend sets the cookie and still accepts the body token, (b) the frontend moves
over, (c) `REFRESH_COOKIE_ONLY` is turned on and the body token is gone. See `DEPLOY.md`.

### Verification
- `python3 -m pytest tests -q` (from `backend/`, against a scratch PostgreSQL 16 instance)
  → **144 passed** (123 after M25 + 19 M26 session cookie + 2 M26 pool pre-ping). Neon
  was not touched.
- `npm test` (in `frontend/`) → **53 passed** (5 files, ~1.5s, no warnings).
- Mutation check on the new M26 guards — every one of them is caught by a test:
  dropping `httponly` → the cookie test fails; dropping the origin check → 4 failures;
  dropping the CSRF check on logout → 2 failures; dropping it on logout-all → 1 failure;
  `SameSite=None` → `lax` → the https cookie test fails; `Secure` → `False` → the same
  test fails; dropping `credentials: 'include'` in the frontend → the api test fails;
  dropping the `X-CSRF-Token` header → the api test fails.
- Mutation check on the new frontend tests: breaking the owner-badge condition fails 2
  tests; posting the wrong owner id fails the transfer test with
  "expected { new_owner_id: +0 } to deeply equal { new_owner_id: 2 }". The tests are not
  vacuous.
- Production check after the M21–M23 deploy (`da5f2b2` backend, `bccc4b8` frontend):
  - Login for one account with a fresh `X-Forwarded-For` on every request → **429 on the
    11th attempt**. Before the fix the same trick produced no throttle at all.
  - A request that carries its own `CF-Connecting-IP` is refused by **Cloudflare** with a
    403 before it reaches the app, so the header the limiter trusts most cannot be forged.
  - Websocket live updates on the deployed backend: `prediction_created`, `pick_updated`,
    `leaderboard_updated` and `prediction_resolved` all arrived on an open socket.
  - Ownership transfer on the deployed backend: join → members → transfer → badge follows →
    non-owner refused (403) → former owner leaves (200) → new owner cannot leave (409) →
    new owner deletes the league (200). 12/12 checks passed.
  - The throwaway probe accounts were deleted from Neon afterwards (5 rows, 0 left).
- Production check after the M26 phase (a) deploy (backend `5eef0d1` + `cf168cc`),
  with a throwaway probe account that was deleted afterwards — **17/17 checks passed**:
  - The deployed API answers a signup with
    `Set-Cookie: frager_refresh=…; HttpOnly; Max-Age=2592000; Path=/api/auth; SameSite=none; Secure`
    and `Cache-Control: no-store` ✓ — the refresh token is now in a cookie that no
    script can read.
  - The body still carries the refresh token and a `csrf_token` (the transition gate is
    off, so an old frontend keeps working) ✓.
  - A refresh with **only** the cookie → `200` with a new access token and a new CSRF
    token ✓.
  - A request from a foreign `Origin` → `403 Origin not allowed` ✓.
  - A logout without the CSRF token → `403 CSRF token missing or invalid`; with it →
    `200 {"ok": true}`; the session is then dead (`401` on refresh) ✓.
  - **The probe found a second bug.** The first request after a quiet period answered
    `500` — the pool handed out a connection that Neon (or the proxy in front of it) had
    closed while it sat idle. Fixed in `cf168cc`: `pool_pre_ping=True` (the pool checks
    a connection before it hands it out) and `pool_recycle=300`. Two new tests, and both
    fail without `pool_pre_ping`.
  - The CORS preflight for `Origin: https://frager-ten.vercel.app` answers
    `access-control-allow-origin: https://frager-ten.vercel.app` with
    `access-control-allow-credentials: true` ✓ — the browser will send the cookie.
- Production check after the M25 deploy (migration `migrate_v25_creator_set_null` on
  Neon → 2 changes, then 0 on a repeat run; backend `f51589b` + `3316bfc`; frontend
  `c6ddd48`), with throwaway probe accounts that were deleted afterwards:
  - **The first probe failed and found a real bug.** Eleven wrong passwords from one
    address also refused the *correct* password that followed — the per-address limit
    counted requests, not failures, and in production Render appends the real client
    address to `X-Forwarded-For`, so every request from one machine shares that bucket.
    Fixed in `3316bfc`: login has no request-count limit, the address is limited by
    failures too (10 a minute), so a correct password is never refused and one machine
    still cannot hammer many accounts. Re-probed: 12 wrong passwords → 10 × `401` then
    `429`, and the correct password right after → `200`.
  - An unknown email is refused exactly like a known one (`429` after 10 failures) — no
    account-enumeration side channel.
  - `change-password`: wrong current password → `400`, the same password → `400`, the
    new one → `200` with a fresh token pair, the old access token → `401`, the old
    refresh token → `401` (revoked), the new access token → `200`.
  - `delete-account`: wrong password → `400`; owning a league with other members →
    `409`; after transferring it → `200 {"ok": true}` and the account is gone (`401` on
    `/api/auth/me`).
  - The void policy on real data: the open prediction of the deleted user survives with
    `creator_id = null` and `status = "void"`, the deleted user's pick is gone, the
    other member's pick stays, and the void prediction moves nobody's points. The
    settled prediction survives with `creator_id = null` and the other member keeps
    their `-5`. The sole-member league is deleted with the account; the league with
    other members stays.
  - Neon after the probes: 10 users, 1 league, 1 prediction — exactly the state before
    them. No probe rows left.
  - The deployed frontend bundle (`index-CBGrzwN5.js`, CSS `index--jAXk-oW.css`) is the
    one built locally, and it contains the account view and the void badge.
- `npm run build` (in `frontend/`) → **build succeeded**.
- `python3 -c "import app.main"` → imports cleanly.
- Live check against a local uvicorn with `FORWARDED_ALLOW_IPS=*` (the Render setting): a
  login with a rotating `X-Forwarded-For` is refused on the 11th attempt, and the same
  account is still capped at 10 attempts a minute even when the address and every header
  are rotated.
- `migrate_v20_sessions` run twice on a legacy schema → changes applied, then 0 change(s);
  also applied to Neon (4 changes, then 0 on a repeat run).
- Production smoke test after the M20 deploy: signup → `me` → refresh → replay → logout-all
  all behaved as designed (probe user deleted afterwards).
- `migrate_v18_cascades` run twice on a legacy schema → 7/7 changed, then 0/7 changed;
  later applied to Neon (7/7, then 0/7 on a repeat run).
- M19 delete tests fail with an FK violation on a DB without the M18 cascade, confirming
  the migration prerequisite is real.
