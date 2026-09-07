# Security model

[Documentation map](README.md) · [Architecture](architecture.md) ·
[Panel runbook](hermes/panel.md)

The office holds one person's mail, messages, notes, and business context, and it runs an agent with
tools next to them. Security here is expressed as **runtime boundaries and recovery rules**, not as
a hope that a model will always choose correctly.

The organising assumption: *assume the model can be confused or steered by content it reads.* Every
boundary below is placed so that a confused model still cannot do the damaging thing.

## What is being protected

| Asset | Where it lives | Worst case if lost |
| --- | --- | --- |
| Personal and work mail | Mailbox provider; digests on the VPS | Full read of the owner's correspondence |
| Telegram session (MTProto) | Private volume, correct owner | Impersonation of the owner across Telegram |
| Bot token | Private deployment state | Publication into the owner's private group |
| Knowledge base and archive | VPS volumes, synced to the Mac | Disclosure of business context and decisions |
| Model provider credentials | Private auth store, never in prompts or cron | Billable abuse; prompt exfiltration |
| Panel credentials and mTLS keys | Split across `private/` paths | Operator access to the whole office |

## Trust boundaries

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/c4-container-dark.svg">
  <img alt="Container diagram showing the public edge, the Hermes agent layer, the execution layer, and the knowledge services as separate trust zones" src="assets/c4-container-light.svg">
</picture>

### 1. The network edge — one door

Exactly one container publishes a port. Caddy terminates TLS on 8451 and demands a **client
certificate** from Benka's own CA; only then does Hermes apply its own dashboard authentication
(scrypt password hash, stable signing secret, HttpOnly/Secure cookies).

Two gates that answer different questions: mTLS asks *is this a known device*, dashboard auth asks
*is this a known operator*. Neither substitutes for the other.

Key material is split so one compromise does not yield the set: the agent container never receives
the server key, the client key, or the CA key, and the CA key is never mounted into Caddy.

Full reasoning in [ADR-0010](adr/0010-single-public-listener-with-mtls.md).

### 2. Domain isolation — four separate offices

`personal`, `work`, `family`, and `sandbox` are not labels on one context. Each is a distinct
manifest with its own file paths, memory, tool permissions, credentials, and delivery targets.

Routing happens **before** tools are attached: the Gateway resolves the sender and route to a
profile, then assembles only that profile's context. An unmatched route gets no tools at all.

Each profile's manifest lives in the private `private/benka-manifests/`, mounted read-only at
`/run/benka/profiles/`. Substituting the shared Gateway manifest is prohibited precisely because it
would collapse the boundary on every plugin call.

Only `personal` currently holds write credentials. `work`, `family`, and `sandbox` remain
read/archive-only until the operator prepares their own verified credential files — a widening that
is an explicit policy change, not a default.

### 3. Tool restriction — least privilege per context

User sessions do not receive the terminal, file, browser, cronjob, or kanban toolsets.

`delegate_task` is permitted only to a single isolated subagent that has **no** terminal, browser,
filesystem, memory, or further delegation.

Background model calls have no tools at all — not a restricted set, none — and no inherited memory
([ADR-0006](adr/0006-bound-background-model-work.md)).

### 4. Container constraints

Read-only root filesystems, dropped Linux capabilities, resource and PID limits, controlled writable
mounts, rotated logs, and **no Docker socket anywhere**. Caddy keeps only `NET_BIND_SERVICE`,
required by the pinned binary's file capability.

The runtime runs as UID/GID 1000. Ownership is deliberately *not* uniform — Redis writes its AOF as
999, OmniRoute writes SQLite as root, Caddy reads the mTLS key through the root group — which is why
[operations](hermes/operations.md#installation) forbids a blanket `chown -R` over production state.

### 5. Delivery containment

A worker may publish only to its configured allowlisted route. **It cannot select a chat or thread
from the content it just processed.**

This is the specific defence against prompt injection reaching an outbound channel: a malicious
email or channel post cannot redirect output, because the destination was never the model's to
choose. The worst case is a wrong message in the right private topic.

### 6. Data provenance

Captures record their source metadata. Raw evidence, editable wiki artifacts, retrieval indexes, and
compact agent memory have separate roles and separate lifetimes
([ADR-0005](adr/0005-wiki-first-capture-rag-as-retrieval.md)).

Whole mailboxes and ordinary conversation are not indexed. Full email bodies are not included in RAG
by default. Each domain's archive receives only that domain's data.

## Secrets

Nothing secret is in Git. Tracked configuration uses `<placeholder>` syntax; real values live in
protected VPS state and the existing encrypted Ansible vault.

The gate is automated. [`scripts/scan-git-secrets.py`](../scripts/scan-git-secrets.py) walks **every
reachable Git blob** plus the working tree, using `detect-secrets --no-verify` so no discovered
credential is ever submitted to a provider. Findings contain hashes and locations, never plaintext.
A reviewed-value allowlist covers the known false positives (algorithm prefixes, test fixtures,
container names), and the scanner has a self-test so a broken scanner cannot pass silently.

The last recorded run before publication: 1,226 objects scanned, 34 reviewed matches, **0
unresolved**.

CI runs this on every push and pull request alongside gitleaks
([ADR-0011](adr/0011-verification-on-the-vps-not-in-ci.md)). Secrets never appear in prompts, cron
command bodies, examples, or shell history.

## Operational rules that are part of the security model

These read like ergonomics and are not:

- **`uncertain` is not `delivered`.** Treating a successful exit code as a confirmed send is how a
  system publishes twice ([reliability](reliability.md)).
- **A certificate expiring authorises nothing.** Time pressure is how careful boundaries get
  bypassed, so the runbook says this explicitly.
- **The activation receipt is an operational interlock, not authorisation.** There is no automatic
  activation generator and no timer anywhere in the project. Only an operator creates one, and only
  after a separate instruction.
- **`/sethome` inside a forum topic** silently redirects notifications for the entire Gateway.
- **Never run a global `docker compose down` or `docker system prune`** — the host runs four
  unrelated projects.

## Known limits

Stated because a security section that claims completeness is not credible:

- The office **is not offline**. Configured model providers and source APIs receive requests. Data at
  rest stays on the host; data in a prompt does not.
- **A single host is a single point of failure**, accepted deliberately
  ([ADR-0001](adr/0001-self-host-on-one-private-vps.md)).
- **Panel certificate refresh is still manual.** Scheduling it with alerting is an open item in the
  [acceptance record](hermes/acceptance.md).
- **Reconciliation depends on a human** reading the queue. Nothing escalates by itself.
- **Full chat against the real models was not verified at cutover**, and the 48-hour observation
  window and full production acceptance remain open.

## Reporting a vulnerability

See [SECURITY.md](../.github/SECURITY.md).

## Related

- [ADR-0001](adr/0001-self-host-on-one-private-vps.md) · [ADR-0010](adr/0010-single-public-listener-with-mtls.md) · [ADR-0011](adr/0011-verification-on-the-vps-not-in-ci.md)
- [Panel runbook](hermes/panel.md) — mTLS, authentication, and certificate maintenance
- [Archived Git and redaction policy](archive/openclaw/08-git-and-redaction-policy.md) — the
  inherited policy record
