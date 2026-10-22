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
DATABASE_URL="<render's database url>" .venv/bin/python -m migrations.migrate_v25_creator_set_null
```

`create_tables.py` and all `migrations/*` scripts are idempotent. Run
`migrate_v18_cascades` once on Neon to switch the core foreign keys to
`ON DELETE CASCADE` (the models already declare it; the script updates an older DB).
This is required before the M19 league-delete endpoint is used — without it,
`DELETE /api/leagues/{id}` fails with a foreign-key violation. It has already been applied
to the current Neon database. Run `migrate_v20_sessions` once on Neon to add
`users.token_version` and the hashed `refresh_tokens` table (required for M20 sessions).
Run `migrate_v25_creator_set_null` once on Neon to make `predictions.creator_id`
nullable with `ON DELETE SET NULL` (required for M25 account deletion: the prediction
survives, nobody owns it).

> **Order matters.** Migrations must run *before* the new code is deployed, because the
> new backend code selects columns that do not exist yet. If you push to `main` first,
> Render deploys within a minute and the API starts throwing `500` on every request that
> touches the changed table (this happened during M20: `POST /api/auth/login` returned 500
> until `migrate_v20_sessions` was applied to Neon). Safe sequence for a new migration:
>
> 1. run the migration against Neon,
> 2. confirm it is idempotent by running it a second time (expect 0 changes),
> 3. only then push the code that depends on it.
>
> **M21–M23 change no tables**, so no migration is needed for them. **M25 does**: run
> `migrate_v25_creator_set_null` before the M25 backend is deployed, otherwise
> `POST /api/auth/delete-account` fails with a foreign-key violation the moment it
> deletes a user.

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

## 5. Deploy order for the frontend

The frontend calls `GET /api/leagues/{id}/members` for the ownership-transfer picker.
That endpoint only exists from M21 onwards, so **deploy the backend before the
frontend**. If the frontend goes first, the transfer dialog reports "Not found" until the
backend is updated; everything else keeps working.

## 5b. The session cookie (M26) — three phases, in this order

From M26 the refresh token lives in an `httpOnly` cookie instead of `localStorage`, and
the frontend keeps the access token in memory only. The rollout has to happen in three
steps, because the two sides have to agree on the transition:

| Phase | What goes out | What it means |
|-------|---------------|---------------|
| (a)   | backend       | the API sets the cookie **and** still hands out / accepts the body refresh token |
| (b)   | frontend      | the app stops using `localStorage` and starts using the cookie |
| (c)   | backend       | `REFRESH_COOKIE_ONLY` is turned on: the body refresh token is no longer returned or accepted |

Never deploy (b) before (a): without the cookie the app cannot restore a session after a
reload. Never deploy (c) before (b): an old frontend still sends the body token and
would be signed out on every reload.

Phase (c) is the code default of `REFRESH_COOKIE_ONLY` (`true` since M26 went live);
the env var can put the body token back for one deploy if a client cannot be updated.

**Check the origin before phase (a).** The cookie is cross-site (Vercel → Render), so it
is `SameSite=None; Secure`, and the backend refuses a mutating auth request whose
`Origin` is not the frontend's. `CORS_ORIGINS` on Render must contain
`https://frager-ten.vercel.app` exactly — one wrong character and every login is
refused with `403 Origin not allowed`. Check it before deploying:

```bash
curl -i -X OPTIONS https://frager-backend.onrender.com/api/auth/login \
  -H 'Origin: https://frager-ten.vercel.app' \
  -H 'Access-Control-Request-Method: POST' | grep -i 'access-control-allow-origin'
```

After phase (a) the API must answer with the cookie:

```bash
curl -i -X POST https://frager-backend.onrender.com/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"...","password":"..."}' | grep -i set-cookie
# frager_refresh=...; HttpOnly; Secure; SameSite=None; Path=/api/auth; Max-Age=2592000
```

After phase (b) the deployed bundle must send the cookie and keep no token in
`localStorage` (check the bundle in `frontend/dist/assets/index-*.js` for
`credentials:"include"` and for the absence of `frager_refresh`).

## 6. Rate limiting and proxies in production

The API sits behind Cloudflare → Render → uvicorn.

- Render sets `FORWARDED_ALLOW_IPS=*` for Python services, so uvicorn trusts every
  proxy and rewrites `request.client` from the **first** `X-Forwarded-For` entry — an
  entry the caller writes. Frager therefore does **not** key its rate limits on
  `request.client.host`.
- Limits key on the signed-in user (JWT subject); the caller's address is only used as a
  secondary layer and is taken from `CF-Connecting-IP` (which Cloudflare overwrites) or
  from the last `X-Forwarded-For` entry (which Render appends). **Login has no
  request-count limit**: it has failure budgets instead — 10 failures a minute per
  account *and* 10 failures a minute per address. A correct password is therefore never
  refused, while one machine still cannot hammer many accounts. (This was found by a
  production probe: with a request-count limit, eleven wrong passwords from one address
  also refused the *correct* password that followed.)
- The counters live in process memory, so they are per instance. Render currently runs a
  single instance; scaling out would need a shared store (Redis).
- After deploying, verify with two probes: repeated *failed* logins for one account must
  return `429` on the 11th failure even when `X-Forwarded-For` changes every time, while
  a correct login always succeeds.

Checked on the deployed service:

- A login with a fresh `X-Forwarded-For` on every request → `429` on the 11th *failed*
  attempt; the same account with the right password still logs in.
- A request that sends its own `CF-Connecting-IP` is refused by Cloudflare with `403`
  before it reaches Render, so that header cannot be forged from the outside.
- The websocket sends `prediction_created`, `pick_updated`, `leaderboard_updated` and
  `prediction_resolved` to an open socket after the matching HTTP call.

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
