# ADR-0010: Expose exactly one public listener, behind mTLS

- **Status:** Accepted
- **Date:** 2026-06-02
- **Context:** [Security](../security.md) · [Panel runbook](../hermes/panel.md) ·
  [Archived security model](../archive/openclaw/07-architecture-and-security.md)

## Context

The office needs an operator surface reachable from outside the host: a browser dashboard for
sessions, settings, and live status.

That surface is the most attractive thing on the machine. Behind it sit the owner's mail, his
Telegram sessions, his knowledge base, and an agent with tools. A password-protected dashboard on
the public internet is a login form that anyone in the world may attempt indefinitely.

The host also runs unrelated projects. Reddit Compass already owns port 8450, an L4/SNI router owns
443, and ACME owns 80. Whatever this project exposed had to fit around infrastructure it does not
own — and must not disturb.

## Decision

**One container has a published listener. Everything else binds internally.**

Caddy terminates TLS on port 8451 and requires a **client certificate** from Benka's own CA before a
request reaches anything. Hermes then applies its own dashboard authentication — scrypt-hashed
password, stable signing secret, HttpOnly/Secure session cookies.

Two independent gates, deliberately: mTLS answers *is this a known device*, dashboard auth answers
*is this a known operator*. Neither substitutes for the other, and the neighbouring project's Basic
Auth is not accepted for Hermes.

Key material is split so no single compromise yields the set. The agent container never receives the
server key, the client key, or the CA key. The CA key is not mounted into Caddy at all.

Containers are constrained beyond the network boundary: read-only root filesystems, dropped Linux
capabilities, resource limits, controlled writable mounts, and **no Docker socket anywhere**. Caddy
retains only `NET_BIND_SERVICE`, required by the pinned binary's file capability.

Verification is negative-first: `verify-hermes-panel-vps.py` checks mTLS refusal, refusal without a
session, refusal on a wrong password, and that a ticket cannot be replayed — before it checks that a
correct login works. Its report contains no endpoint, cookie, or credential.

## Alternatives considered

**Dashboard behind password auth only.** Standard practice. Rejected because it leaves an
unauthenticated attack surface permanently reachable; mTLS means an unknown client never reaches the
application at all.

**VPN or SSH tunnel, no public listener.** Strictly the most secure, and the predecessor used a
tunnel for the OpenClaw UI. Rejected as the primary path because it makes routine access depend on
tunnel setup per device; mTLS with a certificate in the system keychain reaches the same trust
boundary while working from a browser.

**Cloudflare Tunnel or a similar zero-trust proxy.** Good properties, less setup. Rejected on
[ADR-0001](0001-self-host-on-one-private-vps.md) grounds: it puts a third party in the path of the
operator surface.

**Reuse the neighbouring project's Caddy and certificate directly.** Less to run. Rejected because it
couples this project's availability to another project's config, and a mistake here would break
someone else's service.

## Consequences

An unauthenticated request never reaches application code, and neither does an authenticated request
from an unknown device.

The blast radius of a compromised container is bounded: read-only root, no capabilities, no Docker
socket, no key material it does not need.

**The cost is certificate operations.** The client certificate is valid for 90 days, and renewal and
revocation are manual operator work. The panel uses a *copy* of the neighbour's certificate, so
renewing the source does not renew the panel — `--refresh-certificate` exists precisely because that
is not automatic, and scheduling it with alerting is still an open item before production
acceptance.

**Access requires a provisioned device.** A new machine cannot reach the dashboard until a
certificate is issued and imported. That is the intended trade.

The dashboard shares the PID and network namespace with the Gateway, because Hermes needs it for
live status. A fully isolated dashboard container was tried and does not work — a real constraint,
recorded rather than glossed.

**A certificate expiring is not an incident that authorises anything.** The runbook says so
explicitly, because time pressure is how careful boundaries get bypassed.
