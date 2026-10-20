# Frager — Cloudroom Prompts

Hand these to a Cloudroom local thread running on `~/projects/frager` (OpenCode).

---

## Milestone 1 — Auth (sign up / log in)

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
