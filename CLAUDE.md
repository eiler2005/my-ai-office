# Claude Code instructions for this repository

Behavioural guidelines to reduce common LLM coding mistakes, plus the rules specific to this
project.

**Tradeoff:** these guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think before coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity first

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports, variables, and functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## 4. Goal-driven execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant
clarification.

---

## Repository role

This repository **is** My AI Office: the Hermes-based personal AI operating layer for Benka, its
integration source, deployment templates, and Git-safe operational records.

**Production has run on Hermes Agent since 2026-09-06.** The recorded status is `ACTIVE_ON_HERMES`;
the 48-hour observation window and full production acceptance remain open in
`docs/hermes/acceptance.md`. Do not describe those gates as closed.

Start with `README.md`, then `docs/README.md` — it is a map with role-based reading paths.

### The predecessor

The system previously ran on OpenClaw. That runtime is **retired**. Its documentation lives under
`docs/archive/openclaw/` as a historical record and its repository is frozen at
[`eiler2005/clawden-ai`](https://github.com/eiler2005/clawden-ai).

- **Never treat anything under `docs/archive/` as current.** It does not describe the running
  system, and its commands do not deploy anything.
- Do not "update" archived documents to match today's system. The archive records what was true
  then; that is its entire purpose.
- Predecessor-era deploy scripts and artifacts still exist in the tree for rollback and migration
  reference. They are marked. Do not run them, and do not use them as a model for new work.
- The migration itself is recorded in `docs/adr/0009-migrate-runtime-to-hermes.md` and
  `docs/hermes/`. Those legitimately name OpenClaw — they are about replacing it.

## Runtime boundary

- Hermes and its integrations run in their own containers under `/opt/benka-hermes` on the Hermes
  VPS. Prepare locally; deploy only when explicitly authorised.
- **Never give the agent the Docker socket, host administration tools, or unrestricted filesystem
  tools.**
- If a tool is needed by the agent or a gateway-executed workflow, install it into the runtime image
  — not onto the host OS — unless the user explicitly asks for a host-level dependency.
- When checking whether a command exists, check the right context: the host OS for
  infrastructure and admin tools, the relevant container for runtime tools.
- The host is shared. Keep `reddit-compass`, `moex-futoi`, `cheap-intelligence`, and `stealth`
  intact. Ports 80 and 443 belong to existing infrastructure. **Never run a global
  `docker compose down`, `docker system prune`, or restart another project's proxy.** See
  `docs/hermes/inventory.md`.
- Production activation requires a separate instruction from Denis, a fresh consistent snapshot, and
  verified shutdown of the old writers. Neither elapsed time nor a successful build authorises it.

## Version pins

- Hermes Agent is a Git submodule pinned to an exact commit; every other dependency is pinned in
  `pyproject.toml` with `uv.lock` committed. See
  `docs/adr/0012-vendor-hermes-as-a-pinned-submodule.md`.
- **`docs/reference/versions.md` is the single place recording what each pin is, whether it is
  current, and how to move one.** Update it — including the Currency date — whenever a pin is
  checked or changed.
- **Moving any pin requires re-running the native-contract checks and the regressions.** A pin bump
  is a change to be verified, not a chore.
- A healthy container, a channel probe, or an outbound-only Telegram delivery does not prove
  Telegram UI ingress. Require a fresh manual inbound-and-outbound smoke before promoting a change
  that touches the Telegram path.

## Security and secrets

- Never commit or quote live values from `LOCAL_ACCESS.md` or anything under `secrets/`.
- Use placeholders instead of real hostnames, passwords, tokens, client certificate details, or SSH
  coordinates in tracked files — including in examples and commit messages.
- Verify with `python3 scripts/scan-git-secrets.py`. CI runs it plus gitleaks on every push.

## Language

English everywhere, with three exceptions: the `обсуди:` trigger keyword, Russian product names in
historical `CHANGELOG.md` entries, and **`workspace/*.md`**.

`workspace/*.md` files are prompt artifacts mounted into the running agent. Benka converses with its
owner in Russian. **Translating them changes production behaviour** — treat them as code, not
documentation. See `CONTRIBUTING.md#language`.

## Documentation

- `docs/` is organised by topic. Only ADRs are numbered; the numbering under `docs/archive/openclaw/`
  is the predecessor's sequence and means nothing today.
- A change to *why* the system works a certain way needs an ADR, not just a doc edit. Never rewrite
  an existing ADR to look better in hindsight — supersede it and change the status.
- Diagram SVGs under `docs/assets/` are **generated**. Edit `scripts/render-diagrams.py` and re-run
  it; never hand-edit an `.svg`, because the light/dark pair will desynchronise.
- Verify links with `python3 scripts/check-docs-links.py`.
- Keep claims bounded. If a check has not been run, say so.

## Git workflow

- **Use explicit staging.** Do not use `git add .`, `git add -A`, `git add --all`, or
  `git commit -a`. A hook blocks these so `secrets/` and `LOCAL_ACCESS.md` cannot be swept in.
- Review `.gitignore` before adding new local-only files.
- If deployment behaviour changes, update the relevant runbook in the same task.

### Deployment

Preparing configs and editing files locally is allowed. **Deploying requires an explicit command.**

## Changelog

- Update `CHANGELOG.md` with every significant change — features, fixes, config changes,
  deployments — in the same task as the change itself.
- Follow [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions.

## Files to keep aligned

When behaviour changes, these must not fall behind:

- `README.md` and `docs/README.md`
- `CHANGELOG.md`
- `docs/architecture.md`, `docs/workflows.md`, `docs/reliability.md`, `docs/security.md`,
  `docs/knowledge.md`
- `docs/reference/services.md` and `docs/reference/schedules.md`
- `docs/hermes/operations.md`, `docs/hermes/acceptance.md`, `docs/hermes/panel.md`
- `docs/adr/` — when the *reason* changes, not just the implementation

## Local-only complements

- `CLAUDE.local.md` for personal notes that should not be committed.
- `.claude/settings.local.json` for local Claude Code overrides that should not be committed.

## Commit permission rule

- **Never create a git commit or push to remote without explicit user approval in the current
  session.**
- Before any `git commit` or `git push`, state what will be committed and ask for confirmation.
- This rule overrides any general "commit when done" instruction.
- One-time approval does not carry over to future commits in the same or other sessions.
