# Frager — Cloudroom Prompts

Hand these to a Cloudroom local thread running on `~/projects/frager` (OpenCode).

---

## Milestone 4 — Resolve + payout + leaderboard

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
