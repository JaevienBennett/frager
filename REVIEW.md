# Review prompt — Claude as a read-only reviewer

Claude's job on this repo is **review**, not implementation. It shares this working tree
with the implementing agent, so it must not be able to write, commit or push.

## Run it — Claude Desktop (primary)

1. Open **Claude** → the **Code** tab (not chat).
2. `Cmd+N` for a new session.
3. In the row under the prompt box:
   - **Environment**: *Local* (not Cloud).
   - **Project folder**: `/Users/og.jae/projects/frager`.
   - **Worktree**: **off**. This repo forbids worktrees — the reviewer and the
     implementer must see the same tree.
   - **Permission mode**: **Plan**. It reads files, runs commands to explore, and
     proposes a plan without editing source.
4. Paste the prompt below and press `Enter`.

`/code-review` also works in the Code tab if you want Claude's own built-in review of
the current diff — useful as a second opinion on the same change, but it does not know
this repo's rules, so the prompt below is the one that reads `CLAUDE.md`.

## Run it — terminal CLI (optional)

The CLI is installed (`~/.local/bin/claude`, 2.1.307) but not signed in. Signing in
needs **nothing from your uncle** — it uses your own account, which already has the
seat:

```bash
claude auth login          # "Claude account with subscription" → your account
cd ~/projects/frager
claude --permission-mode plan
```

Faster and more precise than the app; the app is fine if you'd rather not sign in twice.

## The prompt

```
Review the diff for <describe the change, or paste `git diff <base>..<head>`>.

Read CLAUDE.md first — it lists the rules this codebase must not break.

Look for, in order of value:
1. Correctness bugs: wrong status code, off-by-one, a race, a case where the value is
   used before it is checked, a place where a failure is swallowed.
2. Security: anything that leaks a secret, an email, or a rate limit that a caller can
   dodge; a SQL string built by concatenation; an endpoint missing its auth check.
3. Contract drift: a frontend caller that expects a field the backend no longer sends, a
   status code the frontend does not handle.
4. Dead code or a leftover debug statement.
5. Tests that would still pass if the behaviour they describe were broken. Say which
   ones and why.

Rules for your answer:
- Do NOT edit any file. Do NOT run git commands that change state. You are reading.
- You MAY run read-only commands: git diff, git log, git show, git status, npm test,
  npm run build, pytest.
- Only report findings you can point at with file:line. No speculation.
- If you find nothing, say so plainly. Do not invent issues to seem thorough.
- Rank findings by severity: BLOCKER, MAJOR, MINOR, NIT.
- For each finding: what breaks, in what scenario, and the smallest fix.
```

## What to do with the answer

- **BLOCKER / MAJOR** → do not merge. Send it back to the implementing agent with the
  finding quoted.
- **MINOR / NIT** → your call; note them in `AUDIT_REPORT.md`.
- **Nothing found** → that is a calibration data point. Say so and move on.

## Why review-only

The implementing agent and the reviewer share one working tree. Two agents writing at
once is how files get clobbered, and this repo forbids branching and worktrees for
exactly that reason. Read-only also means the reviewer can be run at any time, including
against a diff that is already pushed — which is how the last few milestones were
checked.

The guard rails, in order of strength:

| Layer | Where | What it stops |
| --- | --- | --- |
| Permission mode | Plan, in the app or `--permission-mode plan` | Claude editing source files |
| Deny rules | `~/.claude/settings.json` + `.claude/settings.json` | Claude reading any `.env`, or running `git push`/`commit`/`checkout`/`switch`/`reset --hard`/`clean`/`rm -rf` |
| Allow rules | `.claude/settings.json` | Claude asking before read-only `git diff/log/show/status`, `npm test`, `npm run build`, `pytest` |
| Project memory | `CLAUDE.md` | Claude breaking the repo's rules even in a read-only session |
