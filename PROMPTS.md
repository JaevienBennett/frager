# Frager — Cloudroom Prompts

Hand these to a Cloudroom local thread running on `~/projects/frager` (OpenCode).

---

## Milestone 0 — Scaffold

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
