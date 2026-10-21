# Frager — Cloudroom Prompts

Hand these to a Cloudroom local thread running on `~/projects/frager` (OpenCode).

---

## Milestone 19 — League management + invite links (DONE)

```
TITLE: Milestone 19 — League management + invite links

GOAL
Let owners rename/delete leagues, let members leave, and make invites shareable as links.

CONSTRAINTS (must follow)
- Do not expose emails (nicknames only)
- Owner-only rename/delete; owner cannot leave (must delete)
- Deletes rely on the M18 ON DELETE CASCADE FKs; do not manually delete children
- Do not run migrations against a shared/production DB without approval
- Do not start long-running servers
- Shared checkout: do not switch branches or commit/stage/push; only edit the assigned files

BACKEND (Cloudroom)
1. backend/app/routes_leagues.py:
   - PATCH /api/leagues/{id}: LeagueUpdate body; missing/non-member -> 404, non-owner -> 403.
   - DELETE /api/leagues/{id}: missing/non-member -> 404, non-owner -> 403; db.delete; -> {"ok": true}.
   - POST /api/leagues/{id}/leave: missing/no membership -> 404, owner -> 409; remove only the
     caller's membership -> {"ok": true}.
2. backend/app/schemas.py: LeagueUpdate with the same trim/1-100 validation as LeagueCreate
   (shared normalize_league_name helper).
3. backend/tests/test_m19_league_management.py: permissions, validation, leave rules, and a
   non-vacuous cascade assertion (memberships/predictions/picks actually gone).

FRONTEND (other agent)
4. frontend/src/App.jsx + styles.css: owner rename/delete, member leave, shareable invite link
   with copy, and `/?join=CODE` pre-fill in the join form.

VERIFY
- `cd backend && DATABASE_URL=<scratch> python3 -m pytest tests -q` -> 45 passed
- `python3 -c "import app.main"` -> OK
- `cd frontend && npm run build` -> OK

RESULT (implemented)
- Backend by Cloudroom (18 tests), frontend + docs by the other agent, branch
  m19-league-management. Verified on a scratch PostgreSQL 16 instance (never touched Neon):
  45 tests pass, build passes. The M18 cascade migration is a hard prerequisite for delete
  (without it: FK violation); it is already applied to Neon.
```

---

## Milestone 18 — Input validation + cascade integrity (DONE)

```
TITLE: Milestone 18 — Input validation + cascade integrity

GOAL
Harden user input and database integrity with small, low-risk changes.

CONSTRAINTS (must follow)
- Do not expose emails (nicknames only)
- Only a prediction's creator may resolve it; resolve once; +stake/-stake; leaderboard derived
- Picks stay gated until the caller has picked or the prediction is resolved
- bcrypt pinned 4.0.1; backend/.env never committed
- Migration must be idempotent (safe to run twice) and PostgreSQL-specific
- Do not run the migration against a shared/production DB without approval
- Do not start long-running servers

BACKEND
1. Validation (backend/app/schemas.py):
   - PredictionCreate.question: trim whitespace, enforce 1-500 chars, reject blank.
   - LeagueCreate.name: trim whitespace, enforce 1-100 chars, reject blank.
2. Cascade deletes (backend/app/models.py):
   - ondelete="CASCADE" on memberships(league_id, user_id), predictions(league_id,
     creator_id), picks(prediction_id, user_id), leagues(owner_id).
   - passive_deletes=True on the owning relationships so Postgres performs the cascade
     instead of the ORM nulling non-null child FKs first.
3. Migration (backend/migrations/migrate_v18_cascades.py):
   - Discover existing FK constraint names dynamically via pg_constraint; do not hardcode.
   - Drop/recreate each target FK with ON DELETE CASCADE.
   - Idempotent: a second run changes nothing and exits 0.
4. Tests (backend/tests/test_m18_validation.py, conftest.py):
   - Blank/whitespace and over-limit question/league name -> 422; valid values -> 201.
   - Cascade checks delete a user/league and assert dependent rows are gone.
   - Test the migration against a throwaway schema and assert idempotency.
   - conftest seeds one user + league only when the tables are empty (needed by M14 tests).

FRONTEND
5. frontend/src/App.jsx: trim + validate the same limits client-side, show inline errors,
   add maxLength={500} / maxLength={100}.

VERIFY
- `cd backend && python3 -m pytest tests -q` -> all green
- `python3 -c "import app.main"` -> OK
- Migration runs twice cleanly
- `cd frontend && npm run build` -> OK

RESULT (implemented)
- Backend by Cloudroom on branch m18-input-hardening (commit 3de5a2e); frontend + docs by
  the other agent. Verified on a scratch PostgreSQL 16 instance (never touched Neon):
  27 tests pass, build passes. Migration is written but NOT yet applied to Neon — see
  DEPLOY.md.
```

---

## Milestone 17 — Auth hardening: password policy, rate limiting, security headers (DONE)

```
TITLE: Milestone 17 — Auth Hardening: Password policy, Rate limiting, Security headers

GOAL
Harden auth and security with minimal risk. Enforce minimum password length, add rate
limiting to auth endpoints, add security headers middleware.

CONSTRAINTS (must follow)
- Do not expose emails to others (nicknames only)
- Preserve all existing behavior unless necessary for security
- backend/.env never committed
- bcrypt pinned 4.0.1
- All tests still pass; frontend build passes
- No long-running servers started

1) PASSWORD POLICY
- Backend: Update `backend/app/schemas.py` - SignupRequest/Credentials? Enforce minimum
  password length. Set `password: str = Field(min_length=8, max_length=128)` for
  SignupRequest and Login (Credentials). Also keep nickname validation as-is.
- Frontend: Update signup/login form in `frontend/src/App.jsx` to enforce min length 8 on
  password (add `minLength={8}` attribute). Also update placeholder text to hint
  "password (8+ chars)".

2) RATE LIMITING
- Add slowapi dependency to `backend/requirements.txt` (`slowapi>=0.1.9`)
- Create `backend/app/rate_limit.py` with a limiter instance (e.g. using
  `Limiter(key_func=slowapi.util.get_remote_address)`)
- Wire limiter in `backend/app/main.py`: add `app.state.limiter = limiter`, exception
  handler for `RateLimitExceeded`
- Apply rate limits to auth endpoints:
  - POST `/api/auth/signup` - e.g. "5/minute"
  - POST `/api/auth/login` - e.g. "10/minute" (to avoid blocking legitimate users while
    deterring brute force)
- Use appropriate decorator/route-based limits. Keep other routes unlimited for now (or
  conservative). Document limits in comments.

3) SECURITY HEADERS
- Add middleware in `backend/app/main.py` to set security headers on all responses:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 0` (modern practice) or omit; prefer modern
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), camera=(), microphone=()`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (safe for HTTPS
    deployments like Render)
- Implement as simple ASGI middleware class or via @app.middleware("http").

4) TESTS & VERIFICATION
- Update smoke tests to use password >= 8 chars (already do in some cases? Check). Current
  test uses "pass123456" (10 chars) - OK.
- All existing tests still pass (M14 + smoke)
- Frontend builds
- Backend imports successfully

DELIVERABLES
- Updated files as needed
- Summary of changes + test/build results
```

---

## Milestone 16 — Real-time updates via WebSockets (DONE)

```
TITLE: Milestone 16 — Real-time updates via WebSockets

GOAL
Add lightweight WebSockets to Frager so leaderboard/predictions update live per spec
("Leaderboard updates live (real-time)"). Keep existing HTTP REST API working (backward
compatible). No breaking changes.

CONSTRAINTS (must follow)
- Only creator resolves predictions
- Resolve once; scoring +stake/-stake; leaderboard derived never stored
- Picks gated until you've picked or resolved
- Emails never exposed (nicknames only)
- backend/.env never committed
- bcrypt pinned 4.0.1
- Do not break existing tests; all must still pass
- Frontend build must pass
- No long-running servers started in report

SCOPE
1) Backend
- Add dependency `websockets` to `backend/requirements.txt`
- Create `backend/app/ws.py` (or similar): connection manager to track connections by
  league_id. Support connect/disconnect/broadcast to all members in a league.
- Add WebSocket endpoint: `GET /ws/leagues/{league_id}`. Authenticate via JWT (browser WS
  cannot set Authorization header easily). Accept token as query param `?token=<jwt>` OR as
  first message; prefer token in query param for simplicity. Validate token, require user is
  member of league, then subscribe.
- Define event types (JSON): e.g. `{"type":"prediction_created","league_id":...,
  "prediction_id":...}`, `{"type":"pick_updated",...}`, `{"type":"prediction_resolved",...}`,
  `{"type":"leaderboard_updated",...}`. Keep payload small (ids only).
- Publish events on mutations in `routes_predictions.py`:
  - create_prediction (after commit): broadcast `prediction_created`
  - make_pick (after commit): broadcast `pick_updated`
  - resolve_prediction (after commit): broadcast `prediction_resolved` + `leaderboard_updated`
- Handle disconnects cleanly, avoid leaking connections. Thread-safe store (simple dict is
  fine for single-process; note Render single instance for now).
- Add CORS/WS handling - no change to existing CORS.

2) Frontend
- In `frontend/src/App.jsx` (LeagueView): when viewing a league, open WebSocket to
  `VITE_API_URL` (or derive ws:// from http://, wss:// from https://). Pass token via query
  param.
- On connect: log minimally; on message: react to event types. For each relevant event for
  current league, trigger refetches.
- Reconnect with exponential backoff on close/error (max ~5s). Stop when leaving league
  (onBack).
- Graceful fallback: if WS unavailable, just rely on existing HTTP behavior (no regression).
- Show no intrusive UI changes; keep existing states.

3) Testing & Verification
- Existing tests must still pass (M14 + smoke). Add minimal smoke test for WS
  import/manager if easy, but not required to hit network.
- Frontend builds (`npm run build`). Backend imports successfully.

DELIVERABLES
- Updated `backend/requirements.txt`
- New `backend/app/ws.py` (WS manager + helpers)
- Modified `backend/app/main.py` to register WS endpoint
- Modified `backend/app/routes_predictions.py` to publish events
- Modified `frontend/src/App.jsx` to add WS client in LeagueView
- Short summary of changes + test/build results
```

---

## Milestone 15 — Audit & gap-fill (DONE)

```
TITLE: Milestone 15 — Audit & Gap-Fill (Frager polish + completeness)

CONTEXT
Frager is a social yes/no prediction app (wager without risk). Repo
https://github.com/JaevienBennett/frager, local ~/projects/frager, branch main.
Stack: React/Vite frontend -> FastAPI backend -> PostgreSQL (Neon). Deploy: Vercel + Render
+ Neon.
M0-M14 done: auth, leagues/invites, predictions+picks+stakes, gated reveal, creator
resolution, derived leaderboard, NFL ESPN auto-resolution.
Spec says v1 includes "Leaderboard updates live (real-time)" with WebSockets (FastAPI).
Also general polish.

GOAL
Do a thorough audit of the codebase against SPEC.md, PROMPTS.md, README.md, current UX, and
common gaps. Propose and implement high-value, low-risk fixes. Prioritize correctness,
safety, and not breaking existing behavior.

CONSTRAINTS (must follow)
- Do not expose emails to non-owners in API responses (nicknames only)
- Only creator resolves predictions (manual). Never allow non-creator to resolve
- Resolve once; scoring remains +stake/-stake; leaderboard derived (never stored)
- Picks gated until you've picked or resolved
- backend/.env never committed
- bcrypt pinned 4.0.1
- New columns require idempotent migrate_v*.py (nullable -> backfill -> NOT NULL only where
  required)
- Auto-resolution must never overwrite manual resolution
- All existing tests must still pass; frontend build must pass

AUDIT AREAS
1) Real-time (WebSockets) - SPEC lists WebSockets for live leaderboard/predictions. Check if
   missing. If feasible with minimal deps, add lightweight WS to push updates on
   pick/resolve/post/create so UI updates without full reload. If not feasible cleanly,
   document why and suggest alternative.
2) API robustness - validation, error messages, 409/403/404 consistency, auth on all
   protected routes, CORS correct
3) Frontend UX - loading states, error handling, empty states, mobile layout, form
   validation, accessibility basics
4) Picks - updating pick before resolve works? Gating correct? Stake validation? Max stake
   enforcement?
5) Leaderboard - correctness of derived calc, sorting (points desc, accuracy desc, user_id
   tie-break)
6) Leagues - invite code security/format, join flow, membership checks everywhere
7) Auth - token expiry/refresh, logout, session persistence, password requirements
8) Predictions - question length, creating with/without game link, resolved state UI
9) Migrations - ensure all migrate_v*.py are idempotent, run safely
10) Tests - add tests for core flows if missing (auth, leagues, predictions, picks, resolve,
    leaderboard). At minimum add smoke tests
11) Security - secrets, SQL injection (SQLAlchemy ORM used), rate limiting? CORS, headers
12) Deployment - check Render/Vercel config assumptions, env vars, build commands
13) Data integrity - foreign keys, cascades, unique constraints
14) Misc - README accuracy, dead code, TODOs/FIXMEs

DELIVERABLES
- AUDIT_REPORT.md with: findings (high/med/low), evidence (file:line), recommendation,
  effort estimate
- Fixes implemented for HIGH priority items only unless explicitly justified. Group commits
  logically.
- If adding WS, keep backward compatible (HTTP fallback)
- Tests for fixed issues
- Frontend build passes, backend tests pass
- Update README if behavior changes materially
```

---

## Milestone 14 — NFL auto-resolution from ESPN game links (DONE)

```
Add optional NFL auto-resolution to Frager: when a prediction is created with an ESPN NFL
game link, the app can look up the final score and settle the prediction automatically.
Auto-resolution must never overwrite a manual resolution.

Backend (FastAPI):
1. Add columns to Prediction: external_game_id, sport, league, home_team, away_team,
   game_time, resolution_source, auto_resolved_at (all nullable).
2. Add an idempotent migration `backend/migrations/migrate_v14_auto_resolve.py`
   (nullable columns -> backfill -> constraints only where required; safe to run twice).
3. Add `backend/app/services/espn_client.py`:
   - extract_nfl_event_id(game_url) -> validates a full espn.com nfl game link
   - fetch_nfl_event(event_id) -> pulls the event JSON
   - parse_nfl_result(event) -> final score / winner
4. Add `backend/app/services/sports_resolver.py` with try_auto_resolve(prediction, db):
   - only for predictions that are still open and have an external_game_id
   - resolves to yes/no based on the away-team score (the "no" side of the question)
   - sets resolution_source = "espn" and auto_resolved_at
   - never overwrite a manual resolution
5. Wire it lazily: on create (if the game is already final) and on read of predictions
   (lazy on-read). No background scheduler needed.
6. Accept an optional `game_url` in the prediction create payload; return 400 on an invalid
   ESPN link.

Frontend (React):
7. Add an optional "game link" field to the post-prediction form, validated client-side
   (must look like an espn.com NFL game link) and shown as a link on the prediction.

Verify: migration runs twice cleanly, tests pass (add backend/tests/test_m14_auto_resolve.py),
frontend build passes. Report files changed + commands. Do not start long-running servers.
```

---

## Milestone 13 — Logo fix: chip-with-question-mark brand mark [presentation only] (DONE)

```
Replace the current checkmark logo with a coin/chip mark that matches the product
(predictions + wagering), not a task app. VISUAL ONLY — no logic/behavior changes.

The current inline Logo component in frontend/src/App.jsx draws a violet checkmark.
Replace its SVG with this "chip with question mark" mark (exact SVG, 32x32 viewBox):

  <svg width="28" height="28" viewBox="0 0 32 32" fill="none" role="img" aria-label="Frager">
    <circle cx="16" cy="16" r="14" fill="var(--accent)" />
    <circle cx="16" cy="16" r="14" stroke="var(--accent-hover)" stroke-width="2" />
    <circle cx="16" cy="16" r="9.5" stroke="#fff" stroke-width="2" stroke-dasharray="3 3" opacity="0.9" />
    <text x="16" y="21.5" font-size="14" font-weight="800" fill="#fff"
          text-anchor="middle" font-family="inherit">?</text>
  </svg>

Requirements:
  - Keep the existing Brand/header/auth placement and sizes; only swap the mark.
  - Use the theme variables (var(--accent) / var(--accent-hover)) so the mark follows the
    design system; the dashed inner ring and "?" stay white.
  - Ensure it looks correct at the header size (~28px) and any smaller inline uses.
  - Do not change the wordmark, header layout, or any other styling/behavior.

Verify: npm run build succeeds. Report the changed file(s) and build output. No
long-running servers.
```

---

## Milestone 12 — Visual identity & game feel (presentation only) [no logic changes] (DONE)

```
Give Frager real personality so it feels like a fun social prediction game, not just a
styled form. VISUAL ONLY — do NOT change fetch calls, state, handlers, routing, text
logic, or behavior. Same features; richer skin. No new npm dependencies.

Scope: signup/login, header, leagues list, league view (predictions + picks + resolve +
results), leaderboard. Keep responsive to ~360px.

1. BRAND MARK + WORDMARK
   - Create a small inline SVG logo component (a simple, bold mark — e.g. a coin/dice or a
     yes/no toggle glyph) in violet (var(--accent)). Give it a compact, recognisable shape;
     keep it ~24–28px. Render a wordmark "Frager" in a heavier weight beside it.
   - Reuse it in the header and on the auth screen.

2. APP HEADER BAR
   - Add a slim top header (sticky) across the authed app: logo + "Frager" on the left,
     and on the right the user's nickname plus a Logout button (btn-secondary, small).
   - White surface, bottom border (var(--border)), subtle shadow. Container stays centered,
     max-width ~720px inside it.
   - On the auth screen, keep a centered card but include the logo/wordmark above the form.

3. YES/NO SEGMENTED TOGGLE (replaces the side <select>)
   - Replace the pick side dropdown with a two-button segmented control: YES and NO.
   - Selected button: YES = success-tinted (green), NO = danger-tinted (red); unselected =
     neutral. Must remain keyboard-accessible (role="group", aria-pressed on each button)
     and preserve the SAME state shape (form.side = 'yes' | 'no') and the same submit shape.
   - This is the only interaction change: clicking a segment sets the side instead of
     choosing from a select. Keep the stake input and Pick button in the same row.

4. WAGER CHIPS
   - Render stakes as a chip/coin pill wherever a stake is shown (the "N pts" next to
     picks, your own-pick marker, and the counts line). Use a small coin glyph (SVG or ●)
     + number, styled as a rounded pill with a soft violet tint (reuse --accent-soft).
   - Keep the raw number visible; do not change any values or math.

5. LEADERBOARD MEDALS + RANKS
   - Add a leading "#" rank column (1-based by the existing order) and show a medal for the
     top three: gold 🥇 / silver 🥈 / bronze 🥉 (or SVG medals with matching tinted circles).
     Rank 4+ shows the plain number.
   - Keep existing sort order and columns (Member, Points, Record, Accuracy). Your own row
     stays highlighted (.me).

6. RESULT "JUICE" (CSS-only, no logic)
   - When a prediction is resolved, animate the outcome banner in with a small pop/scale
     (e.g. @keyframes pop { from { transform: scale(.96); opacity: 0 } to { transform:
     scale(1); opacity: 1 } }), respecting prefers-reduced-motion (disable animation).
   - On a pick's point swing, add a subtle emphasis (brief highlight/scale) via a CSS
     animation. Do NOT implement a JS counter — a CSS pulse is enough; leave the number
     text unchanged.
   - Add a gentle hover lift (translateY(-1px) + slightly stronger shadow) on cards and
     primary buttons. Respect prefers-reduced-motion.

7. EMPTY STATES
   - Leagues list when empty: friendly card with a line like "No leagues yet — create one
     and invite friends." plus the create form.
   - League view when there are no predictions: "No predictions yet. Post the first one!"
     Keep it short and warm (light, playful tone is fine).
   - Do not invent features; these are just copy + a small SVG/emoji accent.

8. ACCENT COHERENCE + TYPOGRAPHY
   - Use the violet accent consistently for the wordmark, links, focus rings, active/selected
     states, and section accents. Keep body text/neutrals calm (don't over-violet the page).
   - Load Inter via @font-face using a Google Fonts <link>? NO — do not add network fonts
     (avoids a dependency and FOUC). Instead set --font to a modern system stack:
     "Inter", system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
     (so it uses Inter if the OS has it, otherwise a clean fallback). Improve the type scale
     (clearer h1/h2 sizes, line-height, letter-spacing on section titles).

Constraints:
  - Preserve every text string EXCEPT where this milestone explicitly adds empty-state copy
    and injects goals (header/logout uses the existing nickname + logout handler).
  - Preserve all data-testid attributes and conditional logic.
  - The ONLY behavioral change permitted is the side selector becoming a segmented toggle
    (same state value, same submit payload).
  - No backend changes. No new npm dependencies. No network font loading.
  - Respect prefers-reduced-motion for all animations.

Verify: npm run build succeeds. Report: files changed, build output, the new look in words,
and explicitly confirm (a) the pick submit payload is unchanged ({side, stake}), (b) no
fetch/state/handler logic changed beyond the side toggle, (c) all data-testids intact.
Do not start long-running servers.
```

---

## Milestone 11 — Visual polish (light theme, indigo/violet accent) (DONE)

```
Make the Frager UI look clean, modern, and pleasant. VISUAL ONLY — do not change any
logic, state, fetch calls, event handlers, or behavior. Same features, prettier skin.

Current state: all styling is inline `style={{...}}` objects inside frontend/src/App.jsx.
Convert to a small, consistent CSS design system.

Step 1 — create frontend/src/styles.css and import it once in frontend/src/main.jsx
(import './styles.css'). Do NOT use a CSS framework or add dependencies.

Step 2 — define a light theme with CSS variables on :root:
  - Accent: indigo/violet (e.g. --accent: #6d28d9; --accent-hover: #5b21b6; a soft tint
    for backgrounds like --accent-soft: #f3f0ff).
  - Neutrals: --bg (#f7f7fb page background), --card (#ffffff), --border (#e5e7eb),
    --text (#1f2937), --muted (#6b7280).
  - Feedback: --danger (#dc2626), --success (#16a34a), --warn.
  - Spacing scale (e.g. 4/8/12/16/24/32) and radii (--radius: 10px).
  - Use a clean system font stack.

Step 3 — add reusable classes and apply them in App.jsx, replacing inline styles:
  - .app (page bg, font), .container (max-width ~720px, centered, padding).
  - .card / .panel: white, 1px border, radius, subtle shadow, padding.
  - .btn, .btn-primary (accent bg, white text, hover darken), .btn-secondary
    (white bg, border), .btn-danger (outline danger). Consistent padding/radius,
    disabled state (reduced opacity, not-allowed cursor).
  - .input, .select: full-width-friendly, border, focus ring in accent color.
  - Forms: label + field spacing, .form-row for side-select + stake input + Pick button.
  - Headings: clear hierarchy (h1 app title, h2 section titles), muted subtitles.
  - Tables: .table with header row (muted uppercase small caps), row borders, right-align
    numeric columns (Points/Record/Accuracy); subtle hover on rows.
  - Badges/pills for YES/NO, status, and the resolved outcome (green YES / red NO tint).
  - .error (danger text), .success (success text), .muted helper text.
  - .mypick marker line: subtle accent-tinted pill so "You picked: ..." stands out.
  - Date/created lines and the counts line styled as muted helper text.

Step 4 — layout niceties:
  - Prediction cards: header row with question + status badge, then counts line, then the
    pick form, then result/marker content. Generous spacing, collapsible section readable.
  - Leaderboard: white card, clean table, highlight the current user's row subtly (e.g.
    accent-tinted background) — you can compare nickname to the logged-in user's nickname.
  - Buttons in a row should align; primary action (Pick / Resolve / Create) uses
    .btn-primary, others use .btn-secondary.
  - Add sensible spacing between sections; make the signup/login screen a centered card.

Constraints:
  - Keep every text string, class hook, data-testid, and conditional rendering EXACTLY as
    is (behavior-preserving). If an element uses inline styles that include dynamic values
    (e.g. color chosen by was_correct), keep those dynamic bits but move static styling to
    classes — e.g. use a className toggled by the condition instead of inline color.
  - No new npm dependencies. No backend changes. No logic changes.
  - Must remain responsive down to ~360px width (cards stack, tables scroll or shrink).

Verify: npm run build succeeds. Report: files changed, build output, and a short
description of the new look + which classes were introduced. Do not start long-running
servers.
```

---

## Milestone 10 — Reliable pick feedback + honest per-user state + clearer leaderboard (DONE)

```
Fix three related problems in the Frager prediction/pick UX. Milestone 10. Frontend-
focused; no backend/API changes needed. Context: a user made a pick that APPEARED to
work but was never saved (a pick request timed out on the free-tier backend), and the
only signal was a small red message at the bottom of the section, far from the pick
form. Also the leaderboard's "Points" and "Correct" columns are easy to misread
(e.g. reading points 2 with 1/1 as "2/2").

PROBLEM 1 — a failed pick must never look saved.
In frontend/src/App.jsx, LeagueView.handlePick currently does `setError(err.message)`
which renders the message at the bottom of the whole section. Change so pick errors
are shown INLINE at the prediction card (right under that prediction's pick form),
not in the page-level error paragraph.
  a. Add per-prediction error state, e.g. `pickErrors` keyed by predictionId (mirror
     the existing `saving` map shape). On failure set pickErrors[id] = message; on a
     new attempt clear it. Render it right under the pick form for that prediction.
  b. On FAILURE: keep the form values (do NOT clear the stake), and word it clearly,
     e.g. "Your pick was NOT saved: <reason>. Please try again."
  c. On SUCCESS: show a brief, unmistakable confirmation near that card, e.g.
     "✓ Pick saved: NO (5 pts)" using a per-prediction "saved" state that clears
     after a few seconds (setTimeout) or on next change. It must be obvious the pick
     registered.

PROBLEM 2 — auto-retry a pick on a transient/network error (cold start).
  d. Wrap the pick POST in the same retry approach used for mount GETs, but ONLY for
     genuine network errors (the NETWORK_ERROR message), NOT for HTTP errors like 409
     (already resolved) or 400/422 (bad input) — those must fail immediately with the
     inline message. Retry e.g. up to 2 extra times with a short backoff, showing
     "Saving…" on the button throughout.
  e. Do NOT auto-retry on 409 (prediction already settled): instead show a clear
     inline message like "This prediction was already resolved — your pick wasn't
     saved." (This is the exact scenario that can bite when someone resolves while
     another user is picking.)
  f. Keep the existing "Saving…" disabled-button behavior; ensure retries don't
     re-enable it mid-retry.

PROBLEM 3 — make the user's OWN pick state obvious without expanding.
  g. In each prediction card (collapsed view), if the current user has a pick on that
     prediction, show a clear line like "You picked: NO (5 pts)". To know this, the
     detail endpoint already returns picks with user_id when visible; but for OPEN
     predictions the caller can only see picks if they have picked — which is exactly
     the case here (your own pick reveals the list). Use that: when details[id] is
     loaded and picks_visible, find pick.user_id === userId and show the line. If the
     details aren't loaded yet, it's fine to omit until expanded — but prefer to load
     detail for predictions so the marker can show. Keep it lightweight.
  h. This line must update after a successful pick (reuse the existing loadDetail call
     already made after a successful pick).

PROBLEM 4 — leaderboard clarity.
  i. Relabel the leaderboard headers so they can't be misread: keep "Member" and
     "Points", and change "Correct" to "Record" with values shown as "1/1"
     (correct/total), and "Accuracy" stays as a %. Consider a title/hint on the
     Record column like "Record (correct / total picks)". Do not change the data.
  j. Keep sorting/behavior identical.

Keep everything else working (counts/stakes line, resolve buttons, reveal-after-pick,
M9 result banner + tick/cross, friendly errors, retry-on-mount).

Report back: full changed files, npm run build result, and a short before/after of
how a failed pick and a successful pick each look now. Do not start long-running
servers.
```

---

## Milestone 9 — Show who was right (DONE)

```
Make it visually obvious who was right after a prediction is resolved. Milestone 9.
Mostly frontend; one tiny backend addition (see item 1). No external APIs — sports
auto-resolution is NOT in this milestone (that's a later milestone). This is only
about DISPLAYING results clearly once a prediction is resolved.

Backend (tiny):
1. The prediction detail endpoint already returns each pick and, once resolved,
   the resolved_outcome. Confirm each pick in the response is enough for the
   frontend to compute correctness (it is: compare pick.side vs resolved_outcome).
   Add NO new endpoints. (If convenient, you MAY add a computed `was_correct: bool
   | null` per pick — null when unresolved — but only if it's clean; otherwise the
   frontend computes it.)

Frontend (React) — LeagueView:
2. For any prediction whose status == "resolved", show a clear outcome banner,
   e.g. a line: "Resolved: YES" (bold, colored: green for yes / red for no, or just
   a strong label). Make correctness obvious.
3. In the expanded picks list, for each pick, when the prediction is resolved:
   - Show a ✓ (green) if pick.side === resolved_outcome, else ✗ (red).
   - Show the point swing for that pick: +stake if correct, -stake if wrong.
     e.g. "jae — YES (stake 2) ✓ +2" or "og — NO (stake 5) ✗ -5".
   - Before resolution, keep the current display (no ✓/✗ yet).
4. Highlight the current user's own pick specially when resolved, e.g. append
   "— that's you: you were right! (+2)" or "— that's you: wrong (-2)".
5. If the resolved prediction still has picks_visible false for some reason (a
   member who never picked), make sure resolved predictions STILL reveal all picks
   to every member (this already works via the resolved rule — just don't regress
   it). The "make your pick to see..." hint should only appear for OPEN predictions.
6. Keep everything else: counts/stakes line, pick form, creator resolve buttons,
   leaderboard, reveal-after-pick, friendly errors.

Report back: full changed files, npm run build result, and a short before/after of
what a resolved prediction looks like now. Do not start long-running servers.
```

---

## Milestone 8 — Fix stake input + clarify counts/stakes (DONE)

```
Fix two related issues in the Frager prediction/pick UI. Milestone 8. Frontend-
focused; a small backend addition is allowed (see item 6). No new product features.

BUG 1 — stake entered doesn't reliably save (e.g. typed 2, saved as 1/0).
Root cause is the controlled number input in frontend/src/App.jsx (LeagueView,
the pick form):
  <input type="number" min="0" placeholder="stake"
         value={(picks[p.id] || {}).stake ?? 0} ... />
The field is pre-filled with 0 and the value is coerced loosely, so a leading 0
or a submit racing the keystroke can persist the wrong number. Fix it properly:
  a. Do NOT pre-fill with 0. Start the input EMPTY (value '' when there's no
     entered stake) and use placeholder "0". Store the raw string in `picks`
     state; do not coerce on every keystroke.
  b. On submit, parse strictly: a helper `parseStake(raw)` that trims, treats ''
     as 0, requires an integer (reject '2.5' or junk with a friendly error),
     and clamps to 0..1000000.
  c. Disable the submit button while a pick request is in flight to avoid the
     double-click / race that can send a stale value. Show "Saving…" on the button.
  d. Keep the select (side) working the same way.

BUG 2 — the "Yes: N · No: N" line is confusing: those are PICK COUNTS (how many
people chose each side), not points. Make the UI unambiguous:
  e. Relabel to make it clear these are votes/picks, e.g.:
     "3 picks · 2 said Yes · 1 said No"  (or similar clear wording).
  f. Also show the TOTAL stake at risk per side, so users see points, not just
     head-counts. This requires the backend list endpoint to return it.

Backend (small addition):
6. Extend the league predictions LIST response (PredictionOut) with two fields:
   - yes_stake: total stake on yes picks for that prediction
   - no_stake: total stake on no picks
   Compute by summing pick.stake for each side. Keep existing yes_count/no_count.
   Do not add names to the list endpoint.

Frontend (rest):
7. In the prediction list, render the clarified counts + total stakes per side,
   e.g. "2 said Yes (10 pts) · 1 said No (5 pts)".
8. Re-test and make sure a stake of 2 actually saves as 2 (show the saved value
   in the revealed picks list: "nickname — YES (stake 2)").
9. Keep reveal-after-pick, resolve, leaderboard, and friendly-error behavior.

Report back: full changed files, npm run build result, and a clear before/after
description of the stake bug fix. Do not start long-running servers.
```

---

## Milestone 7 — Nicknames + reveal picks after you pick (DONE)

```
Add nicknames and make other members' picks visible to a user after that user has
made their own pick (and always once the prediction is resolved). Milestone 7.
Reuse existing patterns (get_current_user, get_db, membership helpers). Keep the
backend API shapes as compatible as possible.

PART A — Nicknames
1. Add a `nickname` column to the User model (string, nullable=False, unique=True,
   indexed). It's the public display name shown to other members (emails should
   stop being shown to other users).
2. Signup must accept and store a nickname:
   - Update the signup endpoint and its Pydantic schema to take { email, nickname,
     password }. Reject a duplicate nickname with 409.
   - Login stays email + password (nickname is only a display name).
   - Validate: nickname 2–24 chars, not blank. (422 on bad input.)
3. MIGRATION (the trap): users table already exists, so create_tables.py will NOT
   add the column. Write an idempotent migrate_v7 script that ALTERs the users
   table to add a nullable `nickname` column first, backfills any existing rows
   (e.g. set nickname to the part of the email before the '@', ensuring uniqueness,
   fall back to 'user-<id>'), then adds the UNIQUE index. Run it against DATABASE_URL
   and confirm the column + unique index exist.
   - Because existing rows have no nickname, add the column NULLABLE, backfill, then
     set NOT NULL + unique index. Do it in that order so it doesn't fail on old rows.
4. Anywhere the API returns a user to another user, return `nickname` (not email).
   Specifically:
   - LeaderboardEntry: replace `email` with `nickname`.
   - The pick detail (PickOut / PredictionDetail): each pick should include the
     picker's `nickname` (so the frontend can label picks). Do not expose emails.
   - UserOut for /api/auth/me may still include email (it's the user's own account).

PART B — Reveal picks after you pick
5. Change the prediction detail endpoint logic:
   - GET /api/predictions/{id} should include the full list of picks ONLY IF:
       (a) the caller has already made a pick on this prediction, OR
       (b) the prediction.status == "resolved".
     Otherwise return the prediction WITHOUT the picks list (so the frontend can't
     leak other people's choices early). Simplest: return `picks: []` plus a boolean
     `picks_visible: bool` so the frontend knows whether to render them or show a
     "make your pick to see what everyone chose" hint.
   - Each visible pick carries: user_id, nickname, side, stake.
6. The league predictions LIST endpoint (GET /api/leagues/{id}/predictions) should
   keep returning only counts (yes_count/no_count) as it does today — do NOT add
   names there (too heavy). Names come from the detail endpoint.

Frontend (React):
7. Signup form: add a nickname field (alongside email + password).
8. In the LeagueView, each prediction becomes expandable: fetch its detail when the
   user opens it (or auto-fetch per prediction). Show:
   - If picks_visible: a list of "nickname — YES/NO (stake N)".
   - If not visible: "Make your pick to see what everyone chose." Once the user
     picks, re-fetch and reveal.
   - Once resolved: always show the picks plus the outcome.
9. Keep counts, pick form, resolve buttons (creator only), and leaderboard working.
   Leaderboard now shows nickname instead of email.
10. Keep the friendly-error/retry behavior from Milestone 6.

Report back: files changed/created with full contents, the exact commands, and
proof via curl: duplicate nickname 409, verify picks hidden before a pick and shown
after, picks shown when resolved, leaderboard uses nickname. Create and delete proof
data. Do not start long-running servers.
```

---

## Milestone 6 — UX cleanup (DONE)

```
Polish the Frager frontend UX. This is Milestone 6 — no backend changes, no new
features, just making the app not look broken to a first-time visitor.

Problem being fixed: the backend is on Render's free tier and "sleeps" after
inactivity. The first request after a sleep can time out, and right now the app
shows a raw red "Failed to fetch", which looks broken. Also there's a leftover
dev-only "Backend: ok" indicator under the title.

Frontend (React) — edit frontend/src/App.jsx:
1. REMOVE the "Backend: ok" health indicator entirely (the <p data-testid=
   "backend-status"> and the fetch of /api/health behind it). It was only for
   early development.
2. Add a small helper `fetchJson(url, options)` that wraps fetch and:
   - Sets a generous timeout (e.g. 60s) using AbortController, since the free
     backend can be slow to wake.
   - THROWS a clear, human-readable Error on network failure — never let the raw
     browser string "Failed to fetch" reach the UI. On a network error, use a
     message like: "Couldn't reach the server. It may be waking up — please try
     again in a moment."
   - On a non-OK response, surface the backend's `detail` message when present
     (keep the current behavior).
3. Use a simple retry for GET requests on mount (e.g. try up to 3 times with a
   short delay, showing "Waking up the server…" as the loading state), so a cold
   start self-heals without the user refreshing.
4. Make ALL existing calls (signup/login, /me, leagues list/create/join,
   predictions list/create, pick, resolve, leaderboard) go through the helper so
   no raw "Failed to fetch" can appear anywhere.
5. Keep the rest of the UI and all existing behavior/structure working.

Do NOT change the backend. Do NOT change any API shapes.

Report back: the updated App.jsx (full contents), confirmation that `npm run
build` passes, and a short note on where the user now sees the friendly message.
Do not start long-running servers.
```

---

## Milestone 5 — Deployment prep (DONE)

```
Prepare Frager for deployment. This is Milestone 5. Do NOT change any features —
this milestone only makes the app configurable and host-ready. The frontend is
deploying to Vercel and the backend to Render; Postgres is Neon (already in use).

Frontend (React):
1. Replace the hardcoded 'http://localhost:8000' in App.jsx with a value read from
   an env var: import.meta.env.VITE_API_URL, falling back to 'http://localhost:8000'
   when it's undefined (so local dev keeps working with zero config).
2. Do the same for any other hardcoded localhost reference in the frontend.
3. Add a frontend/.env.example containing: VITE_API_URL=http://localhost:8000
4. Make sure the app still builds with `npm run build` and still works locally
   with no .env present (falls back to localhost).

Backend (FastAPI):
5. CORS currently allows only http://localhost:5173. Make the allowed origins
   configurable via an env var CORS_ORIGINS (comma-separated), falling back to
   the current localhost values. Add CORS_ORIGINS to backend/.env.example.
6. Add a production start command that binds to the port Render provides: use
   uvicorn with $PORT. Document it.
7. Add a `backend/render.yaml` or a short DEPLOY section in README describing:
   - backend: root dir backend/, build `pip install -r requirements.txt`,
     start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - env vars needed: DATABASE_URL, SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES,
     CORS_ORIGINS
8. Add a top-level DEPLOY.md explaining the whole setup: Neon (already done),
   Render for the backend, Vercel for the frontend, and that VITE_API_URL on
   Vercel must point at the Render URL, and CORS_ORIGINS on Render must point at
   the Vercel URL. Include the exact dashboard steps (no CLI).

Do NOT commit any real secrets. .env stays gitignored. Only .env.example files
get committed.

Report back: files changed/created with full contents, and confirmation that
`npm run build` and `python -c "import app.main"` both still succeed.
Do not start long-running servers.
```

---

## Milestone 4 — Resolve + payout + leaderboard (DONE)

```
Add resolution and a league leaderboard to Frager. This is Milestone 4 — the payoff
milestone. Auth (M1), leagues (M2), and predictions/picks (M3) exist. Reuse
get_current_user, get_db, membership helpers, and the existing routers/patterns.

Product rules (locked):
- Only the prediction's CREATOR may resolve it. Anyone else gets 403.
- A prediction can be resolved ONCE. Resolving an already-settled prediction is 409.
- Scoring is stake-based and simple:
    A pick on the WINNING side earns +stake points.
    A pick on the losing side earns -stake points.
    Picks with stake 0 just don't move the needle (still count as correct/incorrect
    for accuracy).
- The outcome is one of "yes" or "no".
- The leaderboard must be COMPUTED FROM settled picks, not stored as a running
  counter. Never keep a mutable points column that can drift — derive it.

Backend (FastAPI):
1. Prediction already has a status column ("open"). Use these statuses:
   "open" -> "resolved". Add a resolved_outcome column (nullable string) and a
   resolved_at (nullable datetime) to the Prediction model.
2. Add endpoint:
   - POST /api/predictions/{prediction_id}/resolve  { outcome: "yes" | "no" }
     * Only the creator (403 otherwise). 404 if unknown. 409 if already resolved.
     * Validates outcome is exactly "yes" or "no" (422 via Pydantic Literal).
   - GET /api/leagues/{league_id}/leaderboard  (members only)
     * Returns, for every member of the league, an entry:
       { user_id, email, points, correct, total, accuracy }
       where points = sum over that user's settled picks of (+stake if the pick
       matches resolved_outcome else -stake); correct = # of matching settled picks;
       total = # of settled picks; accuracy = correct/total (0.0 if total == 0).
     * Sort by points DESC, then accuracy DESC, then user_id ASC.
     * Include clearly all members even if they have 0 settled picks (points 0).
3. Make sure the pick endpoints still refuse picks on a non-"open" prediction
   (add a 409 if someone tries to pick a resolved prediction — this is a small
   addition to the M3 pick handler).
4. Add Pydantic schemas: ResolveRequest (outcome: Literal["yes","no"]),
   LeaderboardEntry.

Frontend (React):
5. In the prediction list, if the current user is the creator and the prediction
   is open, show "Resolve Yes" / "Resolve No" buttons. Show the outcome + status
   once resolved.
6. In the league view, add a Leaderboard section that shows each member's email,
   points, correct/total, and accuracy %, sorted.
7. Keep everything else working.

IMPORTANT: update the tables in the database. create_tables.py only creates
missing tables — it will NOT add new columns to the existing predictions table.
So you must ALTER TABLE predictions to add resolved_outcome and resolved_at
(e.g. run the ALTER statements yourself against DATABASE_URL, or add a tiny
migration script). Then confirm the columns exist.

Report back: files changed/created with full contents, exact commands, and proof
(resolve, double-resolve 409, non-creator 403, pick-on-resolved 409, leaderboard
reflects the right points/accuracy) with curl. Create and delete proof data.
Do not start long-running servers.
```

---

## Milestone 3 — Predictions (DONE)

```
Add predictions to Frager. This is Milestone 3. Auth (M1) and leagues (M2) exist —
reuse get_current_user, get_db, and the membership helper/pattern. Do NOT add
resolution or leaderboard logic yet (that is Milestone 4); a prediction can be
created and people can make picks, but nothing is settled in this milestone.

Backend (FastAPI):
1. Add models in app/models.py:
   - Prediction: id (int PK), league_id (FK -> leagues.id, not null, indexed),
     creator_id (FK -> users.id, not null), question (string, not null),
     status (string, default "open"), created_at (datetime).
   - Pick: id (int PK), prediction_id (FK -> predictions.id, not null, indexed),
     user_id (FK -> users.id, not null), side (string: "yes" or "no", not null),
     stake (int, default 0, not null), created_at (datetime).
     Add a UNIQUE constraint on (prediction_id, user_id) — one pick per user.
2. Rules:
   - Only members of a league may create a prediction in it or make picks in it.
     Reuse the membership check from routes_leagues.
   - stake must be >= 0. Use integer points for now.
   - side must be exactly "yes" or "no" (reject anything else with 422/400).
3. New APIRouter (prefix /api), all endpoints require authentication:
   - POST /api/leagues/{league_id}/predictions   { question } -> create (members only)
   - GET  /api/leagues/{league_id}/predictions   -> list predictions in the league
     (members only), each with id, question, status, creator_id, created_at, and
     counts: yes_count, no_count.
   - POST /api/predictions/{prediction_id}/pick  { side, stake } -> create/replace
     the caller's pick. 404 if prediction unknown or caller not a league member.
     If the caller already picked, update it (200) rather than error.
   - GET  /api/predictions/{prediction_id}       -> prediction detail with its picks
     (members only).
4. Add Pydantic schemas (PredictionCreate, PredictionOut, PickCreate, PickOut).

Frontend (React):
5. Inside a selected league (click a league to "open" it), show:
   - A form to post a new prediction (question).
   - A list of the league's predictions with Yes/No counts.
   - On each prediction, a way to pick a side and enter an optional point stake.
6. Keep auth, leagues list, and health indicator working.

IMPORTANT: actually CREATE the new tables — update create_tables.py, RUN it against
DATABASE_URL, and confirm predictions and picks exist.

Report back: files changed/created with full contents, exact run commands, and proof
(create prediction, two users pick, duplicate pick updates, non-member blocked,
bad side rejected) with the curl commands. Create and delete proof data afterward.
Do not start long-running servers.
```

---

## Milestone 2 — Leagues (DONE)

```
Add leagues to Frager. This is Milestone 2. Auth (Milestone 1) already exists —
reuse get_current_user, get_db, and the existing patterns. Do NOT add predictions yet.

Backend (FastAPI):
1. Add two models in app/models.py:
   - League: id (int PK), name (string, not null), invite_code (string, unique,
     indexed, not null), owner_id (FK -> users.id, not null), created_at (datetime).
   - Membership: id (int PK), league_id (FK -> leagues.id), user_id (FK -> users.id),
     created_at (datetime). Add a UNIQUE constraint on (league_id, user_id) so a user
     can't join the same league twice.
   - The league owner should automatically be a member when the league is created.
2. Generate invite_code server-side (e.g. secrets.token_urlsafe(6)); never accept it
   from the client on create.
3. Add an APIRouter (prefix /api/leagues), all endpoints require authentication:
   - POST /api/leagues              { name } -> creates league, returns { id, name,
     invite_code, owner_id, member_count }
   - GET  /api/leagues              -> list leagues the current user is a member of
   - GET  /api/leagues/{id}         -> league detail (members only; 404 otherwise)
   - POST /api/leagues/join         { invite_code } -> joins the league; 404 if the
     code is unknown, 409 if already a member; makes the user a member
4. Add Pydantic schemas (LeagueCreate, LeagueOut, JoinRequest) in schemas.py.
5. IMPORTANT: actually CREATE the new tables. Update create_tables.py (it already
   does Base.metadata.create_all) and RUN it against the database so leagues and
   memberships exist. Confirm the tables afterward.

Frontend (React):
6. After login, show a "Leagues" section:
   - A form to create a league (name) -> then show the invite code prominently.
   - A field to join a league by invite code.
   - A list of the user's leagues (name + member count + invite code).
7. Keep the existing auth UI and health indicator working.

Report back: files changed/created with full contents, the exact commands to run,
and proof that create -> join (as a second user) -> list works end-to-end
(show the curl commands). Create your proof users and delete them afterward.
Do not start long-running servers.
```

---

## Milestone 1 — Auth (DONE)

```
Implement authentication for the Frager backend and wire it into the frontend.
This is Milestone 1. Add ONLY auth — no leagues, no predictions yet.

Backend (FastAPI):
1. Add a User model (SQLAlchemy) in app/models.py:
   - id (int, primary key)
   - email (string, unique, not null, indexed)
   - password_hash (string, not null)
   - created_at (datetime, defaults to now)
2. Add password hashing with passlib[bcrypt]. Never store plaintext passwords.
3. Add JWT auth using python-jose[cryptography]. Create:
   - POST /api/auth/signup  { email, password } -> creates user, returns an access token
   - POST /api/auth/login   { email, password } -> verifies, returns an access token
   - GET  /api/auth/me      -> returns the current user (requires a valid Bearer token)
4. Reject signup if the email already exists (409). Reject login on bad credentials (401).
5. Put a SECRET_KEY and token expiry in config read from env vars (add them to .env.example).
6. Add a get_current_user dependency that decodes the JWT and loads the user.
7. IMPORTANT: actually CREATE the users table. Add a create_all (or a small
   create_tables script) and run it against the database so the table exists.
   Use the existing DATABASE_URL from .env.

Frontend (React):
8. Add simple signup and login forms (email + password). On success, store the
   token in localStorage and show "Logged in as <email>".
9. Add a logout button that clears the token.
10. On load, if a token exists, call GET /api/auth/me and show the logged-in state.
11. Keep the existing "Backend: ok" health indicator.

Dependencies: add passlib[bcrypt], python-jose[cryptography], python-multipart
to requirements.txt. Add any needed npm packages (plain fetch is fine, no axios).

Report back: files changed/created with full contents, the exact commands to run
the backend and frontend, and proof that signup + login + /api/auth/me work
(e.g. the curl commands you'd use). Do not start long-running servers.
```

---

## Milestone 0 — Scaffold (DONE)

```
Scaffold a new full-stack web app called Frager. This is Milestone 0: get a
minimal end-to-end skeleton running locally (frontend talks to backend, backend
talks to a database). Do not build any features yet.

Stack:
- Backend: FastAPI (Python)
- Database: PostgreSQL
- Frontend: React (Vite)

Create this structure:
frager/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI app with a GET /api/health endpoint
│   │   ├── database.py      # SQLAlchemy engine + session to PostgreSQL
│   │   └── models.py        # empty Base for now
│   ├── requirements.txt     # fastapi, uvicorn, sqlalchemy, psycopg2-binary, python-dotenv
│   └── .env.example         # DATABASE_URL placeholder
├── frontend/
│   ├── (a standard Vite + React app)
│   └── src/App.jsx          # calls the backend /api/health and displays "Backend: ok" or the error
├── .gitignore               # python + node
└── README.md                # how to run both parts locally

Requirements:
1. Backend GET /api/health returns {"status": "ok"}.
2. Frontend fetches http://localhost:8000/api/health on load and shows the result.
3. Enable CORS on the backend so the React dev server (localhost:5173) can call it.
4. Use a DATABASE_URL env var (default to a local postgres URL). Do NOT hardcode credentials.
5. Provide exact run commands for both backend and frontend in the README.
6. Do NOT create the database or run migrations — just the connection setup.

Report back: the full file tree you created, the contents of each file, and the
exact commands to run the backend and frontend. Do not start any servers.
```
