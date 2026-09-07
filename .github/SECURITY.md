# Security policy

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/eiler2005/my-ai-office/security/advisories/new)
on this repository. That channel is monitored by the maintainer.

Please include what you found, how to reproduce it, and what you think the impact is. If you are not
sure whether something counts, report it — a false alarm costs a few minutes, and the alternative
does not.

This is a personal project maintained by one person. Expect an acknowledgement within a few days
rather than within hours.

## What is in scope

This repository publishes integration source, sanitised deployment templates, and documentation. In
scope:

- **A secret in the repository or its history.** Credentials, tokens, private hostnames,
  certificates, or personal data that should never have been committed. This is the highest-priority
  category.
- **A vulnerability in the integration code** under `src/benka_integrations/` or `artifacts/` — for
  example a path traversal in wiki ingestion, or an injection through source content.
- **A deployment template that is insecure by default** — a container constraint, network boundary,
  or permission in `deploy/` that would expose a real deployment.
- **Documentation that instructs a reader to do something unsafe.** A runbook that leaks a
  credential if followed is a real vulnerability.

## What is out of scope

- **The live deployment.** The running office is private infrastructure. It is not a target, and it
  is not authorised for testing. Please do not probe any host you find referenced.
- **Upstream projects.** Report issues in [Hermes Agent](https://github.com/NousResearch/hermes-agent),
  [LightRAG](https://github.com/HKUDS/LightRAG), [Redis](https://github.com/redis/redis),
  [Telethon](https://github.com/LonamiWebs/Telethon), or Caddy to those projects. If an upstream
  issue changes how this repository should configure them, that part is in scope here.
- **Model provider behaviour.** Prompt injection *against a model* is a property of models. Prompt
  injection that crosses one of this system's boundaries — reaching a tool, a filesystem, or an
  outbound delivery route — is very much in scope.
- **Accepted trade-offs that are already documented.** The [security model](../docs/security.md)
  states its known limits: a single host, manual certificate refresh, manual reconciliation, and the
  fact that configured providers do receive requests. Please read that section before reporting; if
  you think a stated limit is worse than documented, say so and explain why.

## Design context

Security here is implemented as runtime boundaries rather than trust in model behaviour: one public
listener behind mTLS plus application auth, four isolated domain profiles, no tools on background
model calls, allowlisted delivery routes a worker cannot choose from content, and no Docker socket
anywhere.

The reasoning is in [`docs/security.md`](../docs/security.md) and
[ADR-0010](../docs/adr/0010-single-public-listener-with-mtls.md). Reports that engage with those
boundaries are the most useful ones.

## Supported versions

This is a single-deployment personal system with no release channel. Only `main` is maintained.
