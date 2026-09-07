# Agent Instructions

Read [CLAUDE.md](./CLAUDE.md) first. It is the source of truth for project role, runtime boundaries,
security rules, deployment constraints, changelog expectations, and git workflow.

@CLAUDE.md

## lean-ctx

Prefer lean-ctx MCP tools over native equivalents for token savings when they are available.

If a local `LEAN-CTX.md` is added later, follow it as the detailed lean-ctx rule source.

## Project Notes

- This repository is **My AI Office** — Benka's Hermes-based operating layer, its integration
  source, and Git-safe operational records. Production has run on Hermes since **2026-09-06**.
- The 48-hour observation window and full production acceptance are still open. Read
  `docs/hermes/acceptance.md` before claiming readiness, and do not describe an open gate as closed.
- The OpenClaw predecessor is retired. Its documentation is archived under `docs/archive/openclaw/`
  as a historical record. Never treat it as current, and never update it to match today's system.
- Start from `docs/README.md` — it maps the documentation by what you are trying to do.
- `workspace/*.md` are prompt artifacts mounted into the running agent, not documentation. They stay
  in Russian on purpose; translating them changes production behaviour.
- Keep tracked files sanitized. Never copy or quote live values from `LOCAL_ACCESS.md`, `secrets/`,
  raw `.env` files, certificates, tokens, or tokenized URLs.
- Deployment to the server is a separate operation. Prepare local files freely, but only deploy after
  an explicit user request.
- Significant operational changes should update `CHANGELOG.md` and the relevant docs in the same
  task.
- Use explicit git staging only; do not use `git add .`, `git add -A`, `git add --all`, or
  `git commit -a`.
