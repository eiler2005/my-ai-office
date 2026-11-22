# Pinned versions

[Documentation map](../README.md) · [Operations](../hermes/operations.md) ·
[ADR-0012](../adr/0012-vendor-hermes-as-a-pinned-submodule.md)

Everything this system runs on is pinned to an exact version. This page is the single place that
records **what those versions are, when they were checked, and how to check them again** — the
commit SHAs alone appear in several documents, but a SHA does not tell a reader whether it is
current.

> [!IMPORTANT]
> Moving any pin here requires re-running the native-contract checks and the regressions
> ([acceptance record](../hermes/acceptance.md)). A pin bump is a change to be verified, not a
> maintenance chore.

## Agent runtime

| | |
| --- | --- |
| **Project** | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) |
| **Pinned commit** | `caafe5389ae585ef77387a962aee05b1bcf17029` |
| **Commit date** | 2026-11-19 |
| **Release tag** | `v0.23.3` |
| **Package metadata** | `0.0.0`; the image install stamp supplies the release version and commit |
| **How it is vendored** | Git submodule at `vendor/hermes-agent`, installed via `[tool.uv.sources]` |

**Currency, checked 2026-11-22:** the latest stable upstream release is
[`v0.23.3`](https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.3), the pinned release.
It descends from the former pin `01ae7a5668ce0fa2efca524a4567cacdd0786c95`
(Hermes `0.21.0`).

The release brings [unified Gateway session ownership and cron changes](https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.0),
as well as changes to prompt caching, compaction, and SQLite persistence. The runtime build uses
the [supported Python 3.14 interpreter](https://github.com/NousResearch/hermes-agent/blob/v0.23.3/pyproject.toml)
and upstream's [pnpm dashboard build](https://github.com/NousResearch/hermes-agent/blob/v0.23.3/Dockerfile).
The Benka lock reconciles the shared Python packages and preserves upstream's Pillow security override.

See the [runtime upgrade rehearsal](../hermes/operations.md#runtime-upgrade-rehearsal) for checks
before promoting a new runtime image.

## Other pins

| Component | Pin | Where it is set |
| --- | --- | --- |
| Last30Days skill | `01812ec1851e5c3d92a9049a41b7da4adbfbcb5d` | `deploy/hermes/Dockerfile`, `artifacts/signals-bridge/Dockerfile` (`ARG LAST30DAYS_COMMIT`) |
| Python | `>=3.14,<3.15`; image pinned by digest | `pyproject.toml`, `deploy/hermes/Dockerfile` |
| Runtime dependencies | Exact `==` pins with `uv.lock` committed | `pyproject.toml` |
| GitHub Actions | SHA-pinned, with the version in a trailing comment | `.github/workflows/` |
| Embedding model | Identity and dimension **3072** — not interchangeable | Private deployment manifest |

Dependabot proposes bumps for the Python and Actions ecosystems weekly. It never merges them, and
the runtime submodule is deliberately outside its scope: that bump is the owner's decision.

## Checking currency

```bash
# What is pinned right now
git submodule status vendor/hermes-agent
git -C vendor/hermes-agent describe --tags
grep -m1 '^version' vendor/hermes-agent/pyproject.toml

# What upstream has released since
curl -s https://api.github.com/repos/NousResearch/hermes-agent/releases/latest \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["tag_name"], d["published_at"])'

# How far behind upstream main the pin has fallen
git -C vendor/hermes-agent fetch origin main
git -C vendor/hermes-agent rev-list --count HEAD..origin/main
```

Record the result of a check by updating the **Currency** line above with its date, whether or not
the pin moves. A version page nobody dates is a version page nobody trusts.

## Moving a pin

1. Read the upstream diff. For an unreleased commit there are no release notes to lean on.
2. Update the submodule and, if needed, `pyproject.toml` / `uv.lock`.
3. Build the candidate and run the full suite on the VPS with
   `scripts/run-hermes-vps-tests.sh`. Every suite must pass; compare the counts against the previous
   recorded run rather than against a number written here, which drifts as tests are added.
4. Re-run the native contract checks: plugin tool registration, paused cron idempotency, and the
   `AIAgent` fixtures.
5. Record the outcome in the [acceptance record](../hermes/acceptance.md) and note any new
   version-specific behaviour in the [drift log](../hermes/drift-log.md).
6. Update this page, including the Currency date.

A healthy container does not prove the bump is safe. For anything touching the Telegram path, a
fresh manual inbound-and-outbound smoke is required before promotion.
