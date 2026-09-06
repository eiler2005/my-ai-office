# Isolated panel alongside Reddit Compass

By Denis's instruction of 2026-09-06 the panel uses the **same `RC_PUBLIC_HOST` on a separate port,
8451**. The address is read from the live `rc-caddy` configuration and stored only in the private
`private/access.json`.

Reddit Compass keeps serving its own HTTPS port 8450. Its DNS, Caddyfile, containers, volumes, and
443 router are not modified; ports 80, 443, and 8450 are never claimed by this project.

## Deployment

`deploy/hermes/compose.panel.yaml` creates only `benka-hermes-panel-dashboard-1` and
`benka-hermes-panel-caddy-1`. The dashboard is attached to a dedicated internal Docker network only,
with no outward access and no access to production secrets, the Gateway, Redis, models, mail,
Telethon, or schedules. Caddy is additionally attached to its own ingress network: Docker will not
publish ports for a container that only has an internal network. The dashboard uses the prebuilt
`web_dist`.

Root filesystems are read-only and resource limits are set. The Docker socket and the host runtime
are not mounted.

Caddy terminates TLS on 8451 and requires a client certificate from Benka's separate CA. After
mTLS, Hermes additionally requires its own password. The built-in basic auth provider is used, with
an scrypt hash and a persistent signing secret; the server stores HttpOnly/Secure session cookies.
Reddit Compass's Basic Auth is not used to sign in to Hermes.

The operator runs `scripts/prepare-hermes-panel.py` through `sudo python3` on the VPS after the
image is built. The script starts no services: it creates
`/opt/benka-hermes/panel-rehearsal/private` with 0700/0600 permissions, copies only the
corresponding server certificate and key from the Caddy volume, and issues a separate client
certificate. The agent container never receives the server key, the client key, or the CA key. The
CA key is not mounted into Caddy. Repeating the initial preparation is refused, so that existing
passwords and client certificates cannot be replaced by accident.

After copying `compose.panel.yaml` and `Caddyfile` into the panel directory:

```bash
sudo docker compose \
  --env-file /opt/benka-hermes/panel-rehearsal/private/panel.env \
  -p benka-hermes-panel \
  -f /opt/benka-hermes/panel-rehearsal/compose.panel.yaml create
sudo python3 /opt/benka-hermes/panel-rehearsal/prepare-hermes-panel.py --trust-panel-proxy
sudo docker compose \
  --env-file /opt/benka-hermes/panel-rehearsal/private/panel.env \
  -p benka-hermes-panel \
  -f /opt/benka-hermes/panel-rehearsal/compose.panel.yaml up -d --no-build
```

`--trust-panel-proxy` accepts forwarded headers only from the CIDR of the panel's own internal
network. This is required for Secure cookies behind a TLS proxy. After the network is recreated,
repeat the setup and restart the dashboard only. A wildcard, or trusting every address, is not used.

Caddy retains only the `NET_BIND_SERVICE` capability: the pinned official binary's file capability
requires it even when listening on port 8443. All other capabilities are dropped.

## Access and verification

The private `access.json` holds the URL and the Hermes password.
`private/client/benka-operator.p12` is the client certificate for import into Keychain; its
container password is in `private/client/p12-password`. These files are transferred over SSH into a
protected directory on the Mac that is excluded from Git. Their contents are never pasted into a
chat.

Do not import the client CA as a trusted server CA: the server uses a valid public certificate.

`scripts/verify-hermes-panel-vps.py` runs on the VPS only. It checks mTLS refusal, API refusal
without a session, an incorrect password, a successful login, the Secure/HttpOnly cookie, the HTML
response, the settings and sessions APIs, the WebSocket upgrade, and that a ticket cannot be
replayed. The report contains no endpoint, cookie, or credentials.

These checks do not confirm a conversation with a model or a connected production bot.

## Certificates and maintenance

The existing `rc-caddy` remains the owner of ACME renewal. The panel uses a separate copy, so
renewing the source certificate does not by itself renew the panel's TLS. The operator runs:

```bash
sudo python3 /opt/benka-hermes/panel-rehearsal/prepare-hermes-panel.py --refresh-certificate
# Only when certificate_changed=true:
sudo docker restart benka-hermes-panel-caddy-1
```

Before replacement the script checks the hostname, that at least seven days of validity remain, and
that the key matches the certificate. A new hostname requires separate verification. The script
never writes into the Reddit Compass volume.

Before production acceptance, schedule this check to run regularly with alerting on failure. **A
certificate expiry is not an instruction to switch OpenClaw → Hermes.**

The client certificate is valid for 90 days; renewing and revoking it is a separate operator
action.

The rehearsal panel is stopped with `docker compose ... stop` scoped to the `benka-hermes-panel`
project only. Never use a global `down`, a prune, a Docker restart, or a restart of the
neighbouring project's Caddy.
