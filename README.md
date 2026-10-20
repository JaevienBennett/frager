# Frager

Minimal full-stack skeleton: FastAPI + PostgreSQL backend, React (Vite) frontend.

## Structure

```
frager/
├── backend/          FastAPI app (GET /api/health)
│   ├── app/
│   │   ├── main.py       FastAPI app + CORS + /api/health
│   │   ├── database.py   SQLAlchemy engine/session from DATABASE_URL
│   │   └── models.py     Base (empty for now)
│   ├── requirements.txt
│   └── .env.example
├── frontend/         Vite + React app
│   └── src/App.jsx       fetches /api/health and shows the result
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL running locally (connection only — no database creation or migrations yet)

## Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # edit DATABASE_URL if yours differs
uvicorn app.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/api/health` → `{"status":"ok"}`

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — it shows `Backend: ok` when the backend is reachable.

## Configuration

`DATABASE_URL` is read from `backend/.env` (see `.env.example`). Default:

```
postgresql+psycopg2://postgres:postgres@localhost:5432/frager
```

Credentials are never hardcoded in the source.
