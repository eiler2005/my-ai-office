# ADR-0012: Vendor Hermes Agent as a pinned Git submodule

- **Status:** Accepted
- **Date:** 2026-08-18
- **Context:** [`.gitmodules`](../../.gitmodules) · [`pyproject.toml`](../../pyproject.toml) ·
  [Operations — installation](../hermes/operations.md#installation)

## Context

The office depends on the agent runtime more deeply than on an ordinary library: it registers a
plugin against its extension API, drives its cron, and calls its Python API for every background
model call. A change in any of those breaks the office rather than one function.

The previous runtime had already taught this lesson expensively. Version drift accumulated into a
compatibility ledger, and a candidate release was evaluated and rejected while production stayed
pinned ([ADR-0009](0009-migrate-runtime-to-hermes.md)). Repeating that with a floating dependency
would repeat the outcome.

There was also a practical constraint: the runtime needs building, not just installing. The
Dockerfile compiles the Hermes dashboard in a Node stage and installs the Python API — which means
the build needs the source tree, not a wheel.

## Decision

Vendor Hermes Agent as a **Git submodule pinned to an exact commit** at
[`vendor/hermes-agent`](../../vendor/hermes-agent), currently
`01ae7a5668ce0fa2efca524a4567cacdd0786c95`, and install it from that path:

```toml
[tool.uv.sources]
hermes-agent = { path = "vendor/hermes-agent", editable = true }
```

Every other dependency is pinned to an exact version in `pyproject.toml` — `redis==5.3.1`,
`telethon==1.43.2`, `httpx==0.28.1`, and the rest — with `uv.lock` committed and builds run as
`uv sync --frozen`. The Last30Days skill is pinned the same way, at
`01812ec1851e5c3d92a9049a41b7da4adbfbcb5d`, with its Reddit and GitHub adaptations applied as
build-time patches.

**Moving any pin requires re-running the native-contract checks and the regressions.** A pin bump is
a change to be verified, not a maintenance chore.

## Alternatives considered

**Install the published package from PyPI with a version constraint.** Normal, and much less
ceremony. Rejected on two counts: the Docker build needs the source tree for the dashboard stage,
and a constraint permits the transitive drift this decision exists to prevent.

**Fork the runtime into this repository.** Full control, and the ability to patch immediately.
Rejected because it makes upstream changes a merge problem forever, and the project explicitly does
not want to own an agent runtime — the point of [ADR-0009](0009-migrate-runtime-to-hermes.md) was to
stop maintaining one.

**Vendor by copying the source in, no submodule.** Simple to clone, no submodule confusion.
Rejected because the upstream relationship becomes invisible: no clean way to see what changed
between pins or to contribute a fix back.

**Track the upstream default branch.** Newest fixes automatically. Rejected outright: an unreviewed
upstream change would reach production through a rebuild, which is precisely the failure the
compatibility ledger documented.

## Consequences

**Builds are reproducible.** A given commit of this repository builds the same runtime today and in
six months, which is what makes the recorded image IDs and the 209-check evidence meaningful.

An upstream change cannot reach production without an explicit, reviewable pin bump.

The upstream relationship stays legible: the submodule points at
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), and its authorship and
licence remain its own.

**The costs are the usual submodule costs.** Cloning requires `--recurse-submodules`, and a clone
without it produces confusing failures — the README's clone command includes the flag for that
reason.

**Security updates are manual.** Nothing pulls an upstream fix automatically, so staying current is
a deliberate, scheduled act rather than a default. Dependabot covers the pinned Python and Actions
dependencies; the runtime submodule is on the owner.

Every pin bump costs a full verification cycle. That is the intended price: it makes upgrading a
decision rather than an accident.
