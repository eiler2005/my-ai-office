# ADR-0011: Verify on the VPS; keep CI to publication safety

- **Status:** Accepted
- **Date:** 2026-09-06
- **Context:** [Acceptance record](../hermes/acceptance.md) ·
  [`scan-git-secrets.py`](../../scripts/scan-git-secrets.py) ·
  [`.github/workflows/`](../../.github/workflows)

## Context

The instinct with a public repository is to wire up CI: run the tests on every push, add a green
badge, deploy from a workflow.

For this system that would be misleading rather than useful. What actually needs verifying is not
"does the Python import" but "does this candidate image behave correctly against real Redis, with a
read-only root filesystem, under 2 CPU and 2 GiB, on the machine it will run on". Those checks are
about the deployment target, and a hosted runner is not it.

Deployment from CI is worse. It would require the repository to hold credentials for a host that
also runs four unrelated projects — putting a production path behind a token in a public repo's
settings, for a system whose entire premise is that the owner's data stays on hardware he controls.

But the repository is public, and that creates a different obligation: nothing secret may ever be
published, and the documentation must not rot into broken links and stale paths.

## Decision

**Functional verification happens on the VPS.** `scripts/run-hermes-vps-tests.sh` builds the
candidate in an isolated Buildx builder and runs the suites in containers with a read-only root, no
production secrets, and 2 CPU / 2 GiB limits. Regressions and native contracts run with
`network=none`; Redis is verified on a separate internal network with no published ports. Test data
is synthetic fixtures only. This produced the recorded **209 passing checks**.

**CI covers publication safety, and only that:**

- `secret-scan` — [gitleaks](https://github.com/gitleaks/gitleaks) over the history, plus the
  project's own `scripts/scan-git-secrets.py`, which walks every reachable Git blob and the working
  tree against a reviewed allowlist and reports hashes and locations, never plaintext.
- `docs` — markdown lint, internal link resolution, anchor resolution, and Mermaid parse checks.

**No deployment workflow exists**, and the repository holds no credential for the VPS. This is
recorded as `D004` in the [drift log](../hermes/drift-log.md) — a constraint set by the owner, not a
gap.

## Alternatives considered

**Full CI: tests, lint, coverage, deploy.** The conventional answer, and the best-looking one.
Rejected on both halves: the tests that matter need the deployment target, and deploy-from-CI puts
production access in a public repository's settings.

**Run the pytest suites in CI as a smoke signal, deploy separately.** Genuinely tempting — a green
badge is a real credibility signal. Rejected as a false one: it would prove the code imports and the
unit tests pass in an environment nothing runs in, while the checks that catch real defects still
happen elsewhere. A badge that overstates what was verified is worse than no badge. Notably, the
first VPS run found three defects — CRLF handling in the Git export, the dashboard build output
path, and a script missing from the test image — that no hosted runner would have surfaced.

**Self-hosted GitHub runner on the VPS.** Would unify the two. Rejected because it installs a
runner with repository access on a host running four unrelated projects, widening exactly the
boundary [ADR-0001](0001-self-host-on-one-private-vps.md) draws.

**No CI at all.** Where the project started. Rejected because a public repository needs an automated
gate against publishing a secret, and documentation this size does not stay link-clean by hand.

## Consequences

The checks that gate a release run where the system actually runs, against real Redis, real limits,
and the real image.

The secret gate is automated and reproducible rather than a habit. The scanner's own self-test runs
too, so a broken scanner cannot pass silently.

Documentation integrity is enforced: the `docs/` restructure moved 26 files and rewrote roughly 90
links, and the link and anchor checks are what make that safe to repeat.

**The costs are honest ones.** Release verification requires VPS access, so a contributor cannot run
the full acceptance suite — which is consistent with a personal system, and the suites themselves
are runnable locally with `uv run pytest`. There is no badge asserting the test suite is green,
because CI does not run it; the [acceptance record](../hermes/acceptance.md) carries the evidence
instead, with its scope stated.

Workflows follow least privilege — top-level `permissions: contents: read`, pinned action SHAs,
explicit timeouts — because a workflow in a public repository is itself an attack surface.
