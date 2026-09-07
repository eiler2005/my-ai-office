# Contributing

This is a personal system, run by one person on one private server. It is published so the
engineering can be read and reused, not because it is looking for feature contributions.

That said: **corrections are genuinely welcome.** If something here is wrong, unclear, or no longer
true, open an issue. A documentation fix that stops the next reader from being misled is the most
useful contribution this repository can receive.

## What this repository is and is not

**It is** integration source, sanitised deployment templates, architecture documentation, decision
records, and operational evidence.

**It is not** a deployable product. Credentials, OAuth state, Telegram sessions, personal notes,
mail, conversation archives, live databases, and certificates are deliberately outside Git. You
cannot clone this and get a running office, and that is intentional
([ADR-0001](docs/adr/0001-self-host-on-one-private-vps.md)).

## Ground rules

### Nothing secret, ever

Tracked configuration uses `<placeholder>` syntax. Never commit or quote live values from
`LOCAL_ACCESS.md` or anything under `secrets/`. No real hostnames, passwords, tokens, client
certificate details, or SSH coordinates in tracked files — including in examples, commit messages,
and shell history.

Verify before you push:

```bash
python3 scripts/scan-git-secrets.py
```

CI runs this plus gitleaks on every push and pull request.

### Explicit staging

```bash
# never
git add .
git add -A
git commit -a
```

A repository hook blocks these. Stage paths explicitly, so `secrets/` and `LOCAL_ACCESS.md` cannot
be swept in by accident.

### Deployment is a separate, explicit act

Preparing configuration and editing files locally is always fine. **Deploying is not**, and neither
is activating anything. Production activation requires a separate instruction from the owner, a
fresh consistent snapshot, and verified shutdown of the old writers. Neither elapsed time nor a
green build authorises it.

## Language

Everything is **English**, with three deliberate exceptions.

| Exception | Why |
| --- | --- |
| The `обсуди:` trigger keyword | It is a literal user-facing command. Translating it breaks it. |
| Russian product names in historical `CHANGELOG.md` entries | They record what actually shipped. Rewriting history is falsification. |
| **`workspace/*.md`** | Predecessor-era prompt artifacts. Hermes does not mount them — the live prompt surface is each profile's `SOUL.md` and its installed skills. Kept in Russian as a behavioural record, for the same reason the archive is. |

`workspace/` is a record, not a live configuration. To change what Benka actually does, edit
[`skills/`](skills/) or the system prompt section in
[`plugin.py`](src/benka_integrations/plugin.py) — those *are* deployed, and changing them changes
production behaviour.

## Documentation conventions

**Structure.** `docs/` is organised by topic. Only ADRs are numbered — the numbering under
`docs/archive/openclaw/` is the predecessor's original sequence and means nothing today.

**Claims are bounded.** If a check has not been run, say so. The
[acceptance record](docs/hermes/acceptance.md) keeps its open gates open on purpose, and a
documentation change must not quietly close one.

**Diagrams.** Use Mermaid for anything that tracks the code — it diffs in review and follows the
reader's theme. The four structural SVG diagrams are generated:

```bash
python3 scripts/render-diagrams.py
```

Edit the generator, never the `.svg` files — they are a light/dark pair produced from one
definition, and hand-editing one desynchronises the other.

**Links.** Relative, and they must resolve:

```bash
python3 scripts/check-docs-links.py
```

**The archive is not editable history.** Documents under `docs/archive/` describe earlier stages.
Fix a broken link if you find one; do not update their content to match the current system, because
the point of the archive is that it records what was true then.

### Adding a decision record

A change that alters *why* the system works the way it does needs an ADR, not just a doc edit. Copy
the template in [`docs/adr/README.md`](docs/adr/README.md), take the next number, and name the file
after the decision rather than the component.

The **Alternatives considered** section is the one that matters. Name the option that was genuinely
tempting and the specific reason it lost. A record with no real alternatives is usually a decision
nobody actually made.

Never rewrite an ADR to look better in hindsight. Supersede it with a new one and change the status.

## Running the tests

```bash
uv sync --frozen --extra test --extra hermes
uv run python scripts/test-hermes.py
```

Use that runner, not bare `pytest`. The suites share module basenames, so each one runs in its own
interpreter with a clean environment and a temporary home — which also stops a test from picking up
a developer's real credentials. A bare `pytest` at the repository root additionally tries to collect
the vendored runtime's own test suite.

Expected result: **221 passing** across five suites (57 · 19 · 21 · 98 · 26). Omitting
`--extra hermes` leaves 6 of them failing on a missing `gateway` module.

The [acceptance record](docs/hermes/acceptance.md) records **209** — that was the count at the
2026-09-06 cutover, and it stays as written because it is a record of that run, not a target to keep
updating.

Note that this is **not** the release gate. Functional verification runs on the VPS against real
Redis, a read-only root filesystem, and real resource limits, because those are the conditions that
catch real defects. CI covers publication safety only — the reasoning is in
[ADR-0011](docs/adr/0011-verification-on-the-vps-not-in-ci.md).

## Commits

Conventional-style prefixes (`docs:`, `fix:`, `feat:`, `chore:`), a subject that says what changed,
and a body that says **why** when the reason is not obvious from the diff.

Update `CHANGELOG.md` in the same change for anything significant — features, fixes, configuration
changes, deployments — following [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

If deployment behaviour changes, update the affected runbook in the same commit. A runbook that
describes last week's system is worse than no runbook.

## Reporting a security issue

Do not open a public issue. See [SECURITY.md](.github/SECURITY.md).
