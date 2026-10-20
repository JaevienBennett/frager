# Frager — Cloudroom Prompts

Hand these to a Cloudroom local thread running on `~/projects/frager` (OpenCode).

---

## Milestone 2 — Leagues (create, invite, join)

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
