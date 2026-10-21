# Frager Audit Report (M0–M14)

Date: 2026-10-20
Repo: /Users/og.jae/projects/frager (main)
Stack: FastAPI + SQLAlchemy + PostgreSQL (Neon), React + Vite, JWT auth (bcrypt pinned), Render/Vercel

## 1) WebSockets / Real-time
- **Spec says:** "Real-time: WebSockets (FastAPI)", v1 includes "Leaderboard updates live (real-time)".
- **Current state:** No WebSocket endpoints, no WS client in frontend. All updates use REST + manual refetches (after pick/resolve/create). 
- **Evidence:** `backend/app/main.py` has no `websockets` imports/routers; `frontend/src/App.jsx` uses `fetchJson`/`fetchJsonWithRetry` only.
- **Recommendation (HIGH):** Add minimal WS for league/prediction updates (e.g. `/ws/leagues/{id}`) broadcasting on pick/resolve/create. Keep HTTP fallback. This is feasible with FastAPI + `websockets` (already a common dep) but adds complexity; if time-constrained, document as gap and add "refresh" UX.
- **Effort:** Med-High. **Risk:** Med (connection management, auth). **Fix suggested:** Implement lightweight pub/sub per league with token auth on connect; broadcast events on mutations. Add frontend WS client with reconnect + fallback to current refetches.

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
- **Gaps (MED):** No form validation for empty question beyond `required`; no debouncing; large lists unvirtualized (small scale fine).

## 4) Picks
- **Update before resolve:** `make_pick` allows updating existing pick (200) if user already picked. **OK**.
- **Gating:** Server-side gating in `get_prediction` - picks hidden until caller picked OR resolved. **OK**.
- **Stake validation:** Schema `ge=0`, frontend clamps/validates. **OK**.
- **Max stake:** Frontend clamps to 1000000; backend has no explicit max (schema allows up to integer). **MED** - add backend max to prevent abuse.
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

## 7) Auth
- **Tokens:** JWT (python-jose), bcrypt via passlib (pinned 4.0.1). **OK**.
- **Session:** localStorage token, /me on load. **OK**.
- **Logout:** Clears token. **OK**.
- **Password requirements:** No explicit complexity beyond non-empty (schema just requires password). **LOW** - consider minimum length.
- **Token expiry:** Configurable `ACCESS_TOKEN_EXPIRE_MINUTES`. **OK**.
- **Evidence:** `app/security.py`, `app/routes_auth.py`, `app/config.py`.

## 8) Predictions
- **Creation:** Works with/without game link (M14). **OK**.
- **Question length:** No max in schema (model allows up to 500 chars). **OK**.
- **Resolved state UI:** Banner + ticks/swing + auto-resolution. **OK**.
- **Only creator resolves:** Enforced. **OK**.

## 9) Migrations
- **Idempotent:** `migrate_v4.py`, `migrate_v7.py`, `migrations/migrate_v14_auto_resolve.py` all use IF NOT EXISTS / NULL checks / backfills. **OK**.
- **Order:** Backfill before constraints where needed. **OK**.
- **Run safely:** Confirmed v14 runs twice cleanly.

## 10) Tests
- **Existing:** Only `backend/tests/test_m14_auto_resolve.py` (unittest-style functions, no pytest). **GAP (MED)** - add smoke tests for auth/leagues/predictions/picks/resolve/leaderboard.
- **Coverage:** Core flows untested. **Recommendation:** Add basic integration tests using TestClient.

## 11) Security
- **Secrets:** .env gitignored, .env.example provided. **OK**.
- **SQL injection:** SQLAlchemy ORM used throughout. **OK**.
- **Rate limiting:** None. **MED** for production (especially auth endpoints).
- **CORS:** Configurable. **OK**.
- **Headers:** No security headers middleware. **LOW**.
- **bcrypt pinned:** 4.0.1 in requirements. **OK**.

## 12) Deployment
- **Config:** `VITE_API_URL` env var, `CORS_ORIGINS` env var, Render start command documented. **OK**.
- **Files:** `backend/render.yaml`, `DEPLOY.md`, `.env.example` files present. **OK**.

## 13) Data Integrity
- **FKs:** Present. **OK**.
- **Cascades:** Not explicitly set (defaults). Usually fine if deletes handled carefully. **LOW**.
- **Unique constraints:** `users.email`, `users.nickname`, `leagues.invite_code`, `memberships(league_id,user_id)`, `picks(prediction_id,user_id)`. **OK**.

## 14) Misc
- **README:** Generally accurate, mentions M14 features partially. **OK**.
- **Dead code/TODOs:** None obvious.
- **Frontend build:** Passes.
- **Backend imports:** Pass.

## High Priority Fixes (implement)
1. **Add backend max stake validation** (schema + route) - prevent abuse, consistent with frontend clamp.
2. **Add basic smoke tests** for core flows (auth, leagues, create prediction/pick, resolve, leaderboard) using TestClient.
3. **Harden pick/update rules** - ensure stake validation on update too (already done via schema).
4. **Add security headers middleware** (optional but good) - low risk.

## Medium Priority
1. **WebSockets** - nice to have for "live leaderboard" per spec; can defer if complex, but worth minimal implementation.
2. **Rate limiting** on auth endpoints.
3. **Password minimum length**.

## Implemented Fixes
See commits/changes below.
