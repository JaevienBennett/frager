# Frager

Full-stack skeleton with auth: FastAPI + PostgreSQL backend, React (Vite) frontend.

## Structure

```
frager/
├── backend/
│   ├── app/
│   │   ├── main.py        FastAPI app + CORS + /api/health
│   │   ├── database.py    SQLAlchemy engine/session + Base
│   │   ├── models.py      User model
│   │   ├── schemas.py     Pydantic request/response models
│   │   ├── security.py    password hashing, JWT, get_current_user, get_db
│   │   └── routes_auth.py /api/auth/signup|login|me
│   ├── create_tables.py   create_all (runs against DATABASE_URL)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/App.jsx        health indicator + signup/login/logout + /me
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL reachable via `DATABASE_URL`

## Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # set DATABASE_URL, SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES
python create_tables.py          # creates the users table
uvicorn app.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/api/health` → `{"status":"ok"}`

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — shows `Backend: ok` and the signup/login forms.

## Configuration

Read from `backend/.env` (see `.env.example`):

```
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/frager
SECRET_KEY=change-me-to-a-long-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

Credentials are never hardcoded in the source.

## API

| Method | Path                  | Auth   | Body                | Success | Errors |
|--------|-----------------------|--------|---------------------|---------|--------|
| GET    | `/api/health`         | —      | —                   | 200 `{"status":"ok"}` | — |
| POST   | `/api/auth/signup`    | —      | `{email, password}` | 201 `{access_token, token_type}` | 409 duplicate email |
| POST   | `/api/auth/login`     | —      | `{email, password}` | 200 `{access_token, token_type}` | 401 bad credentials |
| GET    | `/api/auth/me`        | Bearer | —                   | 200 `{id, email, created_at}` | 401 missing/invalid token |
