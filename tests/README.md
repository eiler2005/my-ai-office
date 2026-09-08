# Tests

These suites cover integration logic offline — permission gates, dispatch, rendering, state and the
cutover tree. They do not start a container, contact a model provider, or touch Telegram.

The strategy behind this layout is in [`docs/testing.md`](../docs/testing.md). This file is the
operator view: what to run, and what each run does not tell you.

## Everything

```bash
uv sync --frozen --extra test --extra hermes
uv run python scripts/test-hermes.py
```

The local gate, run before every change. It executes all five suites, each in its own interpreter
with a scrubbed environment and a temporary working directory, then prints a per-suite summary. It
does not build an image, and it is not the release gate.

Observed 334 passing across 28 test modules on 2026-09-08.

## One functional area

```bash
uv run python scripts/test-hermes.py --list
uv run python scripts/test-hermes.py --suite hermes
uv run python scripts/test-hermes.py --suite email --suite signals
```

Use this while working on one part of the system. Run the full set before proposing the change —
`production.py` and the artifact bridges share configuration shapes, so a narrow run can miss the
consequence of a change.

### Hermes core

```bash
uv run python scripts/test-hermes.py --suite hermes
```

[`tests/hermes/`](hermes/) — the activation interlock and everything gated by it: manifest loading,
standby and rehearsal refusals, the container entrypoints, queue slot identity and crash recovery,
worker dispatch and its private logs, the isolated model subprocess, delivery allowlists, snapshot
and restore, and the production cutover tree. This is where a change to `src/benka_integrations/`
belongs.

### Email

```bash
uv run python scripts/test-hermes.py --suite email
```

[`artifacts/agentmail-email/tests/`](../artifacts/agentmail-email/tests/) — the poll prefilter and
digest rendering, including the mailbox footer and poll batching. Uses recorded message shapes; it
never contacts AgentMail.

### Telegram digest

```bash
uv run python scripts/test-hermes.py --suite telegram
```

[`artifacts/telethon-digest/tests/`](../artifacts/telethon-digest/tests/) — reader cursors, the
scheduled window, scoring and content mix, summariser validation, post links, and worker stats. It
does not authenticate a Telethon session or read a real channel.

### Signals

```bash
uv run python scripts/test-hermes.py --suite signals
```

[`artifacts/signals-bridge/tests/`](../artifacts/signals-bridge/tests/) — the largest suite: config
validation, startup lock recovery, source health, Telethon session retry, lookback, matching,
delivery and state, the Last30Days digest and the radar redesign, plus model fallbacks.

### Wiki import

```bash
uv run python scripts/test-hermes.py --suite wiki
```

[`artifacts/wiki-import/tests/`](../artifacts/wiki-import/tests/) — the importer and the embeddings
path, including the local embedding fallback. It does not reach LightRAG.

## On the VPS

```bash
CANDIDATE_TREE=<40-char tree sha> ./scripts/run-hermes-vps-tests.sh
```

**The release gate.** It refuses to run outside `/opt/benka-hermes/candidates/*`. It builds the
candidate on an isolated Buildx builder, then runs the suites, the native contract checks, the
importer rehearsal, `benka status`, a compose config check, and a real Redis restarted mid-run — all
with a read-only root filesystem, no network, and explicit CPU, memory and pid limits. Reports land
in `/opt/benka-hermes/reports/<revision>/`.

Do not run this locally, and do not treat a green offline suite as a substitute.

## What Tests Do Not Cover

- Telegram ingress. A container that is healthy and a delivery that succeeds outbound still prove
  nothing about a message from a person arriving. A manual inbound-and-outbound smoke is required
  before promoting any change on the Telegram path.
- Real model provider behaviour, quality, or cost.
- Real Redis persistence across a restart — that runs on the VPS.
- `production.finalize()`, which hardcodes `/opt/benka` image paths.
- The deploy and backfill shell scripts, which act on a live host.
- The vendored runtime in `vendor/hermes-agent/`, which ships its own suite.

For those, see [`docs/hermes/acceptance.md`](../docs/hermes/acceptance.md) and
[`docs/hermes/operations.md`](../docs/hermes/operations.md).

## Adding a test

Conventions are in [`docs/testing.md`](../docs/testing.md#conventions-for-new-tests). In short: name
the invariant rather than the function, say why in the module docstring — naming the incident and its
date for a regression — keep it offline, and register any new suite in `SUITES` in
[`scripts/test-hermes.py`](../scripts/test-hermes.py).
