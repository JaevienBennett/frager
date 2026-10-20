# Frager

**A social prediction game — wagering without the risk.** Create private leagues with
friends, post yes/no predictions, optionally stake points, and climb a leaderboard that
rewards being right. No real money, ever.

A full-stack web app: React frontend, FastAPI backend, PostgreSQL database — built and
deployed end to end.

![Frager screenshot](docs/screenshot.png)

- **Live app:** https://frager-ten.vercel.app
- **API:** https://frager-backend.onrender.com

---

## What it does

- **Accounts** — sign up with an email, a public nickname, and a password.
- **Leagues** — create a private league and invite friends with a short invite code.
- **Predictions** — anyone in a league posts a yes/no question.
- **Picks** — members pick a side and optionally stake points.
- **Reveal** — you can only see everyone else's picks *after* you've made your own
  (or once the prediction is resolved), so nobody can snipe the crowd.
- **Resolve** — the creator settles the outcome.
- **Results & leaderboard** — correct picks earn `+stake`, wrong picks lose `−stake`;
  a derived leaderboard ranks members by points, then accuracy.

## Tech stack

| Layer     | Choice                          |
|-----------|---------------------------------|
| Frontend  | React (Vite)                    |
| Backend   | FastAPI (Python)                |
| Database  | PostgreSQL                      |
| Auth      | JWT (python-jose) + bcrypt      |
| Hosting   | Vercel (frontend) · Render (API) · Neon (DB) |

## Architecture

```
React (Vercel)  ──HTTP/JSON──▶  FastAPI (Render)  ──SQLAlchemy──▶  PostgreSQL (Neon)
   localStorage JWT              /api/... routers                    users, leagues,
                                 bcrypt + JWT auth                    memberships,
                                                                      predictions, picks
```

- **Auth:** passwords are bcrypt-hashed; access is via a signed JWT sent as a Bearer token.
- **Authorization:** league endpoints verify membership; only a prediction's creator may resolve it.
- **Leaderboard is derived, not stored:** it is computed from settled picks on every request,
  so it can never drift out of sync.
- **Anti-snipe:** the pick list is gated server-side — you can't see others' picks until you
  commit your own (or the prediction is resolved).

## Project layout

```
frager/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, CORS, health
│   │   ├── database.py          SQLAlchemy engine/session + Base
│   │   ├── models.py            User, League, Membership, Prediction, Pick
│   │   ├── schemas.py           Pydantic request/response models
│   │   ├── security.py          hashing, JWT, get_current_user, get_db
│   │   ├── membership.py        is_member / require_member helpers
│   │   ├── routes_auth.py       /api/auth/*
│   │   ├── routes_leagues.py    /api/leagues/*
│   │   └── routes_predictions.py /api/leagues/{id}/predictions, /api/predictions/*
│   ├── create_tables.py         create_all against DATABASE_URL
│   ├── migrate_v4.py            ALTER predictions (resolution columns)
│   ├── migrate_v7.py            ALTER users (nickname, backfill + unique index)
│   └── requirements.txt
└── frontend/
    └── src/App.jsx              auth, leagues, league view, picks, leaderboard
```

## Running locally

**Prerequisites:** Python 3.10+, Node 18+, and a PostgreSQL `DATABASE_URL` (a free
[Neon](https://neon.tech) database works).

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # set DATABASE_URL, SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES
python create_tables.py              # create tables (and run migrate_v*.py on existing DBs)
uvicorn app.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/api/health` → `{"status":"ok"}`

### Frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

The frontend reads its API URL from `VITE_API_URL` (falls back to `http://localhost:8000`).

## API

All league/prediction endpoints require a `Bearer` token. Emails are never exposed to
other users — only nicknames.

| Method | Path                                     | Body                     | Success | Errors |
|--------|------------------------------------------|--------------------------|---------|--------|
| GET    | `/api/health`                            | —                        | 200 `{"status":"ok"}` | — |
| POST   | `/api/auth/signup`                       | `{email, nickname, password}` | 201 `{access_token}` | 409 email/nickname taken |
| POST   | `/api/auth/login`                        | `{email, password}`      | 200 `{access_token}` | 401 bad credentials |
| GET    | `/api/auth/me`                           | —                        | 200 `{id, email, nickname}` | 401 |
| POST   | `/api/leagues`                           | `{name}`                 | 201 league | 401 |
| GET    | `/api/leagues`                           | —                        | 200 user's leagues | 401 |
| GET    | `/api/leagues/{id}`                      | —                        | 200 league (members) | 404 |
| POST   | `/api/leagues/join`                      | `{invite_code}`          | 200 league | 404 unknown code, 409 already a member |
| POST   | `/api/leagues/{id}/predictions`          | `{question}`             | 201 prediction | 404 non-member |
| GET    | `/api/leagues/{id}/predictions`          | —                        | 200 list w/ counts + stakes | 404 non-member |
| POST   | `/api/predictions/{id}/pick`             | `{side, stake}`          | 201 new / 200 updated | 404, 409 resolved, 422 bad side/stake |
| GET    | `/api/predictions/{id}`                  | —                        | 200 detail (picks gated by `picks_visible`) | 404 |
| POST   | `/api/predictions/{id}/resolve`          | `{outcome}`              | 200 resolved | 404, 403 non-creator, 409 already resolved |
| GET    | `/api/leagues/{id}/leaderboard`          | —                        | 200 members ranked (points/record/accuracy) | 404 non-member |

## Notes

- **Free-tier hosting:** the API sleeps after inactivity, so the first request can take
  ~30–60s to wake. The frontend shows a friendly "Waking up the server…" state and
  auto-retries, rather than failing.
- **Deployment:** see [DEPLOY.md](DEPLOY.md) for the Neon + Render + Vercel setup.
