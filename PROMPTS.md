# Frager — Cloudroom Prompts

Hand these to a Cloudroom local thread running on `~/projects/frager` (OpenCode).

---

## Milestone 9 — Show who was right (✓/✗, outcome, point swing)

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
