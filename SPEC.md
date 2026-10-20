# Frager — Project Spec

**Frager** (friendly + wager) — a social prediction game. Wagering without the risk:
predict outcomes with friends, optionally wager points, climb a leaderboard. No money, ever.

## Goal of the build
A **learning project**: full-stack web app (auth, database, API, frontend, real-time, deploy).
Chosen because it teaches software engineering skills beyond data analysis.

## Roles
- **Owner (Jaevien):** product decisions, scope, quality control, verification.
- **Cloudroom (OpenCode agent):** writes the code.
- **Assistant (me):** scoping, precise agent prompts, verification, unblocking.

## Stack (locked)
- **Frontend:** React
- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL
- **Real-time:** WebSockets (FastAPI)
- **Deploy:** Railway / Render / Fly.io (free tier) — later milestone

## v1 scope (locked)
1. Sign up / log in (auth)
2. Create a private league
3. Invite via link; join
4. Post a yes/no prediction
5. Pick a side, optionally wager points
6. Creator resolves → points pay out
7. Leaderboard updates live (real-time)

**Out of scope for v1:** sports API auto-scoring, chat, public feed, custom prediction types,
mobile app, payments.

## Milestones
- **M0 — Scaffold:** repo, project structure, backend + frontend run locally, DB connected.
- **M1 — Auth:** sign up, log in, session persists.
- **M2 — Leagues:** create, invite link, join.
- **M3 — Predictions:** post yes/no, pick a side, optional points.
- **M4 — Resolve + Leaderboard:** resolve → payout → live leaderboard.
- **M5 — Deploy:** live, multi-user.

## Repo
`github.com/JaevienBennett/frager` (public, like credit-risk-model).
