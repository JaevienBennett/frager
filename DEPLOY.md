# Deploying Frager

Three pieces, three services:

| Piece     | Where          | Notes                                        |
|-----------|----------------|----------------------------------------------|
| Database  | Neon (Postgres)| Already provisioned; `DATABASE_URL` in use   |
| Backend   | Render (web)   | FastAPI app in `backend/`                    |
| Frontend  | Vercel         | Vite/React app in `frontend/`                |

The only cross-wiring: the frontend must know the backend URL, and the backend
must allow the frontend's origin. Never commit real secrets — `.env` files stay
gitignored; only `.env.example` files are committed.

## 1. Neon (already done)

Your Neon database is live and `backend/.env` points at it locally. On Render you
will paste the same `DATABASE_URL` as an environment variable. To create tables
after the first deploy, run once from your machine against production:

```bash
cd backend
DATABASE_URL="<render's database url>" .venv/bin/python create_tables.py
```

(Or run it locally against Neon now — `create_tables.py` is idempotent, and
`migrate_v4.py` too if the DB predates Milestone 4.)

## 2. Backend on Render

`backend/render.yaml` is committed, so Render can import it — but the manual
dashboard steps are:

1. Go to https://dashboard.render.com → **New** → **Web Service**.
2. Connect the Frager GitHub repo and select it.
3. Render detects Python. Set:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Under **Environment**, add (values in parentheses are yours to fill):
   - `DATABASE_URL` (your Neon connection string — the same one in `backend/.env`)
   - `SECRET_KEY` (generate one: `openssl rand -hex 32`; Render can also
     auto-generate it via `generateValue` in render.yaml)
   - `ACCESS_TOKEN_EXPIRE_MINUTES` = `60`
   - `CORS_ORIGINS` = your Vercel URL, e.g. `https://frager.vercel.app`
     (add it after you create the Vercel app; comma-separate multiple origins)
5. **Create Web Service**. Note the URL Render gives you,
   e.g. `https://frager-backend.onrender.com`.

## 3. Frontend on Vercel

1. Go to https://vercel.com/new → import the Frager GitHub repo.
2. Set **Root Directory** to `frontend` (Vercel should auto-detect Vite).
   Framework preset: Vite. Build: `npm run build`. Output: `dist`.
3. Under **Environment Variables**, add:
   - `VITE_API_URL` = your Render URL, e.g. `https://frager-backend.onrender.com`
4. **Deploy**. Note the Vercel URL, e.g. `https://frager.vercel.app`.

## 4. Close the loop

- On **Render**, set `CORS_ORIGINS` to the exact Vercel URL
  (`https://frager.vercel.app`, no trailing slash) and restart the service.
- On **Vercel**, make sure `VITE_API_URL` matches the Render URL exactly
  (no trailing slash — the app calls `${VITE_API_URL}/api/...`).
- Open the Vercel URL: you should see `Backend: ok`. Sign up, create a league,
  and you're live.

## Local development (unchanged)

No env files needed locally:

```bash
# backend — reads backend/.env, CORS defaults to http://localhost:5173
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# frontend — VITE_API_URL unset, falls back to http://localhost:8000
cd frontend && npm run dev
```

Copy `backend/.env.example` and `frontend/.env.example` if you want to override
anything; both apps fall back to sensible localhost defaults without them.
