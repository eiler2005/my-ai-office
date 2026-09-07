## What changed

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The reason, if it is not obvious from the diff. What was wrong, or what became possible? -->

## Checklist

- [ ] **No secrets.** `python3 scripts/scan-git-secrets.py` passes. No real hostnames, tokens,
      credentials, certificate details, or personal message content — including in commit messages.
- [ ] **Links resolve.** `python3 scripts/check-docs-links.py` passes.
- [ ] **Staged explicitly.** No `git add .` / `-A` / `commit -a`.
- [ ] `CHANGELOG.md` updated, if this is a significant change.

<!-- Delete any section below that does not apply. -->

### If this changes deployment or runtime behaviour

- [ ] The affected runbook is updated **in this PR** — a runbook describing last week's system is
      worse than no runbook.
- [ ] Verification was run on the VPS, and the [acceptance record](../docs/hermes/acceptance.md)
      reflects it. Open gates stay open.
- [ ] No open gate was quietly closed. If a claim got stronger, the evidence for it is in the diff.

### If this changes *why* the system works the way it does

- [ ] An ADR was added or superseded (`docs/adr/`), with a real **Alternatives considered** section.
- [ ] No existing ADR was rewritten to look better in hindsight.

### If this touches documentation

- [ ] English, except the three documented exceptions in
      [CONTRIBUTING](../CONTRIBUTING.md#language).
- [ ] `docs/archive/` content left as-is — it records what was true then, not what is true now.
- [ ] Diagram SVGs regenerated with `python3 scripts/render-diagrams.py`, not hand-edited.
