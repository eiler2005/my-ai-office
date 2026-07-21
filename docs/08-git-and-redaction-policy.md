# Git And Redaction Policy

This folder is intended to become a safe operational repository, but only after strict redaction discipline.

## Commit policy

### Safe to commit

- project documentation
- redacted config examples
- redacted auth/profile examples
- `.gitignore`
- `CLAUDE.md`
- `.claude/settings.json`
- `.claude/hooks/*.sh`
- `.claude/hooks/README.md`
- helper scripts that do not embed secrets

### Never commit

- anything under `secrets/`
- `LOCAL_ACCESS.md`
- `CLAUDE.local.md`
- `.claude/settings.local.json`
- raw `.env`
- raw OpenClaw auth profiles
- client certificate files
- certificate passwords
- tokenized access URLs
- private keys, PEMs, and ad hoc token files

## Existing protections in this folder

[`.gitignore`](/Users/DenisErmilov/aiprojects/openclaw_firststeps/.gitignore) already blocks:

- `LOCAL_ACCESS.md`
- `secrets/`
- common key/token file types
- temporary logs and scratch files

## Recommended Git workflow

Prefer explicit staging over broad staging.

Good:

```bash
git add README.md docs/ artifacts/ .gitignore
git diff --cached
```

Avoid:

```bash
git add .
git commit -a
```

Repository guardrails now reinforce that preference:

- `CLAUDE.md` instructs AI agents to use explicit staging
- `.claude/settings.json` installs shared Claude Code protections
- project hooks deny broad staging commands such as `git add .`, `git add -A`, and `git commit -a`

## Pre-commit checklist

Before every commit:

1. run `git status`
2. inspect `git diff --cached`
3. confirm no secret-like strings or local-only files were staged
4. confirm docs use placeholders instead of live access details
5. confirm redacted artifacts still contain no passwords, tokens, or certificate material

## If a secret is staged but not committed

Unstage it immediately:

```bash
git restore --staged <path>
```

Then move it under `secrets/` or another ignored location.

## If a secret was already committed or pushed

Treat it as exposed.

Immediate response:

1. rotate or revoke the secret first
2. remove it from history
3. coordinate with every clone before pushing rewritten history

Recommended GitHub guidance:

- GitHub recommends rotating the credential first, then using history rewriting only if needed
- if history must be rewritten, use `git-filter-repo` carefully and coordinate with collaborators

Sources:

- https://docs.github.com/removing-sensitive-data
- https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories
- https://docs.github.com/en/code-security/getting-started/best-practices-for-preventing-data-leaks-in-your-organization

## Recommended repository settings once published

If this becomes a real GitHub repository:

- keep it private by default
- enable secret scanning
- enable push protection
- enable branch protection on the default branch
- require pull request review if more than one person will touch the repo

## AI-project specific documentation rule

For AI infrastructure repos, documentation should always make the following explicit:

- runtime model/provider dependencies
- auth/bootstrap assumptions
- trust boundaries
- local-only vs tracked materials
- rollback path
- version pinning strategy
- version-specific compatibility records for upstream adaptations, with sanitized failure signatures
  and promotion/rollback gates
- runtime boundary between host OS and application container

The tracked [OpenClaw Version Compatibility Ledger](22-openclaw-version-compatibility-ledger.md)
must preserve the reason for each local workaround without copying real chat identifiers, credentials,
hostnames, raw logs, or private configuration into Git.

Shared-VPS incident documentation follows the same rule: record sanitized
probe status, unit ownership and next action only. Do not commit firewall
sources, provider-console screenshots, raw journal excerpts, container IDs,
addresses or generated client artifacts. The required safe handoff is
[Shared VPS incident contract](23-shared-vps-incident-contract.md).

## Claude Code project policy

This repository uses Claude Code-compatible project files to reduce repeat mistakes:

- `CLAUDE.md` for concise project instructions
- `.claude/settings.json` for shared permissions and hooks
- `.claude/hooks/` for lightweight automation guardrails

These committed files must remain:

- secret-free
- short and maintainable
- focused on project-wide rules rather than personal preferences

## Claude Code references

The committed Claude Code guardrails in this repository were aligned to the official Claude Code documentation:

- project instructions and `CLAUDE.md`: https://code.claude.com/docs/en/memory
- project settings and permission rules: https://code.claude.com/docs/en/settings
- hook configuration and hook security guidance: https://code.claude.com/docs/en/hooks

This repository structure now reflects that rule.
