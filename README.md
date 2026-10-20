# Frager

Full-stack skeleton with auth: FastAPI + PostgreSQL backend, React (Vite) frontend.

## Structure

```
frager/
├── backend/
│   ├── app/
│   │   ├── main.py        FastAPI app + CORS + /api/health
│   │   ├── database.py    SQLAlchemy engine/session + Base
│   │   ├── models.py      User, League, Membership, Prediction, Pick
│   │   ├── schemas.py     Pydantic request/response models
│   │   ├── security.py    password hashing, JWT, get_current_user, get_db
│   │   ├── membership.py  is_member / require_member helpers
│   │   ├── routes_auth.py /api/auth/signup|login|me
│   │   ├── routes_leagues.py /api/leagues...
│   │   └── routes_predictions.py /api/leagues/{id}/predictions, /api/predictions/...
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
| POST   | `/api/leagues`        | Bearer | `{name}`            | 201 `{id, name, invite_code, owner_id, member_count}` | 401 |
| GET    | `/api/leagues`        | Bearer | —                   | 200 list of the user's leagues | 401 |
| GET    | `/api/leagues/{id}`   | Bearer | —                   | 200 league (members only) | 404 non-member/unknown |
| POST   | `/api/leagues/join`   | Bearer | `{invite_code}`     | 200 league, joined | 404 unknown code, 409 already a member |
| POST   | `/api/leagues/{id}/predictions`   | Bearer | `{question}` | 201 prediction | 404 non-member |
| GET    | `/api/leagues/{id}/predictions`   | Bearer | —           | 200 list with `yes_count`/`no_count` | 404 non-member |
| POST   | `/api/predictions/{id}/pick`      | Bearer | `{side, stake}` | 201 new / 200 updated | 404 unknown/non-member, 422 bad side/stake |
| GET    | `/api/predictions/{id}`           | Bearer | —           | 200 detail with picks | 404 non-member |
