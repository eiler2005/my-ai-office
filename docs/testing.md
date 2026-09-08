# Testing

Most of what can go wrong here is not a wrong answer from a function. It is a container that starts
without the authority to start, a job that runs under a permission nobody granted, a credential that
reaches a log, or a cutover that writes a tree an operator cannot safely delete. So the tests are
built around **refusals**: what each layer declines to do, and what it declines to reveal.

The suite runs **offline and deterministically** — no network, no model provider, no real Redis, and
a scrubbed environment with a temporary home so a developer's own credentials cannot be picked up.
That makes it fast and safe to run constantly. It also means it is **not the release gate**. Real
defects here have come from the conditions a hosted runner does not have: a read-only root
filesystem, real memory limits, a real Redis restart, line endings in an exported tree. Those are
verified on the VPS, against the actual candidate image. The reasoning is in
[ADR-0011](adr/0011-verification-on-the-vps-not-in-ci.md).

## Test pyramid

```text
        Manual surface smoke          (real Telegram, by hand)      docs/hermes/acceptance.md
              ^
        VPS container verification    (real Redis, read-only root)  run-hermes-vps-tests.sh
              ^
        Native contract checks        (isolated Hermes home)        verify-hermes-contract.py
              ^
        Integration suites            (offline, fakeredis, stubs)   test-hermes.py --suite ...
              ^
        Unit and regression suites    (offline, fastest)            test-hermes.py
```

## Tiers

- **Unit and regression suites** — assert the invariant a single function owes the system, and pin
  the incidents that have already happened once. Every regression test names its incident in the
  module docstring, so a future reader can tell a rule from a scar. Examples:
  [`tests/hermes/test_delivery_targets.py`](../tests/hermes/test_delivery_targets.py) (the
  Last30Days topic that never reached the allowlist),
  [`tests/hermes/test_rag_scan.py`](../tests/hermes/test_rag_scan.py) (a LightRAG 409 that aborted a
  whole scan), [`tests/hermes/test_tool_errors.py`](../tests/hermes/test_tool_errors.py) (an
  undiagnosable Knowledgebase failure).
- **Integration suites** — drive a whole path against **stubbed** externals so real logic runs with
  no live target: `fakeredis` for the queue, a local `ThreadingHTTPServer` speaking the model's own
  HTTP/SSE protocol in
  [`tests/hermes/test_model_native.py`](../tests/hermes/test_model_native.py), a stub `run_agent`
  module in [`tests/hermes/test_model_child.py`](../tests/hermes/test_model_child.py), and a
  synthetic restored snapshot in
  [`tests/hermes/test_production_prepare.py`](../tests/hermes/test_production_prepare.py).
- **Native contract checks** — confirm the vendored runtime still exposes the plugin, cron and
  `AIAgent` surfaces this project builds on, in an isolated Hermes home. This is what a submodule pin
  bump has to re-run: [`scripts/verify-hermes-contract.py`](../scripts/verify-hermes-contract.py).
- **VPS container verification** — build the candidate on an isolated Buildx builder and run
  everything in containers with a read-only root, no production secrets, and 2 CPU / 2 GiB limits,
  including a real Redis restarted mid-run to prove persistence and recovery. **This is the release
  gate**: [`scripts/run-hermes-vps-tests.sh`](../scripts/run-hermes-vps-tests.sh).
- **Manual surface smoke** — a person sends a message to a Telegram surface and reads the reply. No
  automated check substitutes for it; see [what is not tested](#what-is-intentionally-not-tested-here).

## Runners

| Runner | Scope | Network | Used by |
| --- | --- | --- | --- |
| [`scripts/test-hermes.py`](../scripts/test-hermes.py) | All five offline suites, one interpreter each | none | **local, every change** |
| [`scripts/test-hermes.py --suite NAME`](../scripts/test-hermes.py) | One functional area | none | local, while working |
| [`scripts/run-hermes-vps-tests.sh`](../scripts/run-hermes-vps-tests.sh) | Candidate image, contract, Redis, compose config | container-internal only | **the release gate, on the VPS** |
| [`scripts/verify-hermes-contract.py`](../scripts/verify-hermes-contract.py) | Plugin, cron and `AIAgent` contract | none | release gate, pin bumps |
| [`scripts/verify-redis-vps.py`](../scripts/verify-redis-vps.py) | Persistence and recovery across a restart | real Redis | release gate |
| [`scripts/verify-hermes-claw-vps.py`](../scripts/verify-hermes-claw-vps.py) | Importer rehearsal on synthetic data | none | release gate |
| [`scripts/verify-hermes-panel-vps.py`](../scripts/verify-hermes-panel-vps.py) | Panel, negatives first: mTLS, session, password, WebSocket | real panel | operator, after panel changes |

The offline runner spawns **one interpreter per suite** on purpose. The four artifact suites share
module basenames — `models.py`, `poster.py`, `state_store.py`, `cron_bridge.py` and
`omniroute_client.py` all collide — so a single process would import whichever one won. The same
wrapper scrubs the environment down to `PATH`, `SYSTEMROOT` and `TMPDIR` and runs from a temporary
directory, which is what stops a dotenv-aware module reading a developer's real credentials.

Suites, by functional area:

| Suite | Directory | Covers |
| --- | --- | --- |
| `hermes` | [`tests/hermes/`](../tests/hermes/) | Safety gates, entrypoints, dispatch, cutover, schedules |
| `email` | [`artifacts/agentmail-email/tests/`](../artifacts/agentmail-email/tests/) | Mailbox polling, prefilter, digest rendering |
| `telegram` | [`artifacts/telethon-digest/tests/`](../artifacts/telethon-digest/tests/) | Read, score, summarise, post |
| `signals` | [`artifacts/signals-bridge/tests/`](../artifacts/signals-bridge/tests/) | Matching, delivery, state, Last30Days |
| `wiki` | [`artifacts/wiki-import/tests/`](../artifacts/wiki-import/tests/) | Importer and embeddings |

## Coverage map

Integration modules, and the suite that owns each. Observed **334 passing across 28 test modules on
2026-09-08** — a measurement of that run, not a target to keep matching.

| Module | What it does | Tests |
| --- | --- | --- |
| `config.py` | Manifest loading, activation interlock, path confinement | [`test_safety.py`](../tests/hermes/test_safety.py), [`test_tool_errors.py`](../tests/hermes/test_tool_errors.py) |
| `service.py` | Container entrypoint and its activation gate | [`test_entrypoints.py`](../tests/hermes/test_entrypoints.py) |
| `cli.py` | The `benka` console script, including the healthcheck | [`test_entrypoints.py`](../tests/hermes/test_entrypoints.py) |
| `pipelines.py` | Job-to-permission derivation, private worker logs | [`test_pipelines.py`](../tests/hermes/test_pipelines.py) |
| `model_child.py` | Isolated model subprocess, provider allowlisting | [`test_model_child.py`](../tests/hermes/test_model_child.py) |
| `models.py` | Bounded agent calls, JSON payload extraction | [`test_safety.py`](../tests/hermes/test_safety.py), [`test_model_native.py`](../tests/hermes/test_model_native.py) |
| `production.py` | Cutover tree, delivery allowlist, schedule refresh | [`test_production_prepare.py`](../tests/hermes/test_production_prepare.py), [`test_delivery_targets.py`](../tests/hermes/test_delivery_targets.py) |
| `migration.py` | Snapshot, restore, rollback delta, claw layout | [`test_safety.py`](../tests/hermes/test_safety.py), [`test_schedules.py`](../tests/hermes/test_schedules.py) |
| `queue.py` | Enqueue, consume, slot identity, crash recovery | [`test_safety.py`](../tests/hermes/test_safety.py) |
| `delivery.py` · `legacy_delivery.py` | Allowlisted sends, uncertain-delivery handling | [`test_safety.py`](../tests/hermes/test_safety.py) |
| `maintenance.py` | Weekly maintenance, RAG scan, archive | [`test_maintenance.py`](../tests/hermes/test_maintenance.py), [`test_rag_scan.py`](../tests/hermes/test_rag_scan.py) |
| `schedules.py` · `job_registry.py` | Cron slot stability, registry slots | [`test_schedules.py`](../tests/hermes/test_schedules.py), [`test_maintenance.py`](../tests/hermes/test_maintenance.py) |
| `profiles.py` | Route preparation, binding validation | [`test_profiles.py`](../tests/hermes/test_profiles.py) |
| `plugin.py` | Per-surface prompt sections, tool error reporting | [`test_surfaces.py`](../tests/hermes/test_surfaces.py), [`test_tool_errors.py`](../tests/hermes/test_tool_errors.py) |
| `archive.py` · `wiki.py` | Diary archive, index and search, wiki writes | [`test_safety.py`](../tests/hermes/test_safety.py), [`test_maintenance.py`](../tests/hermes/test_maintenance.py) |
| `production.finalize()` | Applies profiles after native claw import | **none** — hardcodes `/opt/benka` image paths; covered on the VPS |
| `last30days_build.py` | Bakes preset data at image build time | **none** — runs in the Dockerfile; a build failure is the check |

## What is intentionally NOT tested here

- **Telegram ingress.** A healthy container, a channel probe, or an outbound-only delivery does not
  prove that a message from a person reaches the agent and comes back. Only a manual
  inbound-and-outbound smoke on the affected surface does, and one is required before promoting any
  change that touches the Telegram path.
- **Real model providers.** Every model test uses a stub or a local protocol server. Provider
  behaviour is not this repository's contract; the transport and the isolation are.
- **Real Redis persistence.** `fakeredis` cannot restart a server.
  [`verify-redis-vps.py`](../scripts/verify-redis-vps.py) does, on the VPS.
- **`production.finalize()`** and anything else that hardcodes container paths. Making these
  testable would mean changing production code to suit the tests; the VPS runs them as they are.
- **The deploy shell scripts** in [`scripts/`](../scripts/). They act on a live host, so a passing
  test would mean less than the runbook it would duplicate.
- **The vendored runtime** in `vendor/hermes-agent/`. It ships its own suite; this project tests the
  contract it depends on, not the dependency.

## CI

CI is scoped to **publication safety** — what must never enter the repository — not to whether the
system works. Two workflows run on every push and pull request:

1. **Secret scan** ([`.github/workflows/secret-scan.yml`](../.github/workflows/secret-scan.yml)) —
   [`scripts/scan-git-secrets.py`](../scripts/scan-git-secrets.py) walks every reachable Git blob and
   the working tree with `detect-secrets`, then `gitleaks` runs as an independent second ruleset.
2. **Docs** ([`.github/workflows/docs.yml`](../.github/workflows/docs.yml)) — `markdownlint-cli2`,
   then [`check-docs-links.py`](../scripts/check-docs-links.py) for internal links and heading
   anchors, then [`render-diagrams.py`](../scripts/render-diagrams.py) with a `git diff` guard so a
   hand-edited SVG fails, then [`check-docs-language.py`](../scripts/check-docs-language.py).

There is deliberately **no test workflow and no deploy workflow**, and the repository holds no
credential for the VPS. Running the offline suite in CI would produce a green badge that says
nothing about the conditions where defects actually appear. See
[ADR-0011](adr/0011-verification-on-the-vps-not-in-ci.md).

## Running locally

```bash
uv sync --frozen --extra test --extra hermes
uv run python scripts/test-hermes.py            # all five suites, the local gate
uv run python scripts/test-hermes.py --list     # what the suites are
uv run python scripts/test-hermes.py --suite hermes --suite signals
python3 scripts/scan-git-secrets.py             # before every push
python3 scripts/check-docs-links.py             # after touching docs/
```

Use the runner, not a bare `pytest`. Running `pytest` at the repository root works — it is
configured to skip `vendor/` — but it collects only `tests/hermes`, in one process, without the
scrubbed environment.

Omitting `--extra hermes` leaves a handful of tests failing on a missing `gateway` module.

## Conventions for new tests

- **Name the invariant, not the function.** `test_the_worker_is_execed_by_absolute_path` says what
  breaks; `test_main` does not.
- **Say why in the module docstring.** For a regression, name the incident and its date. A reader
  months from now needs to tell a deliberate rule from a scar, and a test whose reason is unrecorded
  is the one that gets deleted when it becomes inconvenient.
- **Prefer the narrowest check that proves the change.** A unit test over a whole-path one.
- **Assert the real boundary.** Where a private tree is enforced by one 0700 root, assert that root
  — not every directory beneath it, which the operating system creates with its own defaults.
- **Stub externals; never reach the network.** New code that calls an external binary or service
  ships a stubbed test so the suite stays offline.
- **A new suite must be registered** in `SUITES` in
  [`scripts/test-hermes.py`](../scripts/test-hermes.py), or nothing will run it.

## Related

- [Contributing](../CONTRIBUTING.md) — how to run the tests as part of a change.
- [Tests README](../tests/README.md) — the per-suite operator view.
- [ADR-0011](adr/0011-verification-on-the-vps-not-in-ci.md) — why verification is on the VPS.
- [Acceptance record](hermes/acceptance.md) — recorded VPS runs and the gates still open.
