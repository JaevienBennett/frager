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

For an **existing** database, also run the idempotent migrations (safe to repeat):

```bash
cd backend
DATABASE_URL="<render's database url>" .venv/bin/python -m migrations.migrate_v14_auto_resolve
DATABASE_URL="<render's database url>" .venv/bin/python -m migrations.migrate_v18_cascades
DATABASE_URL="<render's database url>" .venv/bin/python -m migrations.migrate_v20_sessions
```

`create_tables.py` and all `migrations/*` scripts are idempotent. Run
`migrate_v18_cascades` once on Neon to switch the core foreign keys to
`ON DELETE CASCADE` (the models already declare it; the script updates an older DB).
This is required before the M19 league-delete endpoint is used — without it,
`DELETE /api/leagues/{id}` fails with a foreign-key violation. It has already been applied
to the current Neon database. Run `migrate_v20_sessions` once on Neon to add
`users.token_version` and the hashed `refresh_tokens` table (required for M20 sessions).

> **Order matters.** Migrations must run *before* the new code is deployed, because the
> new backend code selects columns that do not exist yet. If you push to `main` first,
> Render deploys within a minute and the API starts throwing `500` on every request that
> touches the changed table (this happened during M20: `POST /api/auth/login` returned 500
> until `migrate_v20_sessions` was applied to Neon). Safe sequence for a new migration:
>
> 1. run the migration against Neon,
> 2. confirm it is idempotent by running it a second time (expect 0 changes),
> 3. only then push the code that depends on it.

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
