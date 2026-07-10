# Claude Code Instructions and rules for working in this project
 
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Repository Role

- This repository is a git-safe operations and handoff package for an OpenClaw deployment on a Hetzner server.
- It is not the live OpenClaw application source tree.
- Start with `README.md`, then use `docs/01-server-state.md`, `docs/02-openclaw-installation.md`, `docs/07-architecture-and-security.md`, and `docs/08-git-and-redaction-policy.md` for deeper context.

## Runtime Boundary

- OpenClaw runs in Docker Compose under `/opt/openclaw` on the Hetzner server.
- If a tool is needed by OpenClaw, its agents, or gateway-executed workflows, install it into the derived OpenClaw image or run it with `docker compose exec`.
- Do not install OpenClaw-adjacent runtime tools on the host OS unless the user explicitly asks for a host-level admin dependency.
- When verifying command availability, check the correct runtime context:
  - host OS for infrastructure/admin tools
  - `openclaw-gateway` container for OpenClaw runtime tools

## OpenClaw Version Compatibility

- Before preparing, building, or deploying an OpenClaw upgrade, read
  `docs/22-openclaw-version-compatibility-ledger.md` together with the current server state.
- Treat every `active-workaround`, `blocked`, or `candidate-held` record as a release gate. Carry an
  active local adaptation into the candidate unless a version-specific validation proves it obsolete.
- Create or update the candidate's ledger record before changing the live image reference. Record the
  known-good rollback image, the required gates, and both positive and negative evidence.
- A healthy container, channel probe, or outbound-only Telegram delivery does not prove Telegram UI
  ingress. For OpenClaw/Telegram changes, require a fresh manual UI inbound-and-outbound smoke before
  promotion.

## Security And Secrets

- Never commit or quote live values from `LOCAL_ACCESS.md` or anything under `secrets/`.
- Keep all documentation sanitized and safe for Git publication.
- Use placeholders instead of real hostnames, passwords, tokens, client certificate details, or raw SSH coordinates in tracked docs.

## Git Workflow

- Use explicit staging in this repo.
- Do not use `git add .`, `git add -A`, `git add --all`, or `git commit -a`.
- Review `.gitignore` before adding new local-only files.
- If deployment behavior changes, update the relevant docs in the same task.

### deployment


It is allowed to prepare configs and edit files locally.  
Deploying is allowed only after an explicit command.

## Changelog

- Update `CHANGELOG.md` with every significant change — new features, fixes, config changes, deployments.
- Do this in the same task as the change itself, before or together with the commit.
- Format: add an entry under `[Unreleased]` or a dated section using [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions.

## Files To Keep Aligned

- `README.md`
- `CHANGELOG.md`
- `docs/01-server-state.md`
- `docs/02-openclaw-installation.md`
- `docs/03-operations.md`
- `docs/05-rollback-and-backup.md`
- `docs/06-command-log.md`
- `docs/07-architecture-and-security.md`
- `docs/08-git-and-redaction-policy.md`
- `docs/22-openclaw-version-compatibility-ledger.md`

## Local-Only Complements

- Use `CLAUDE.local.md` for personal notes that should not be committed.
- Use `.claude/settings.local.json` for local Claude Code overrides that should not be committed.

## Commit Permission Rule

- **Never create a git commit or push to remote without explicit user approval in the current session.**
- Before any `git commit` or `git push`, state what will be committed and ask for confirmation.
- This rule overrides any general "commit when done" instructions.
- One-time approval does not carry over to future commits in the same or other sessions.
