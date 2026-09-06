#!/usr/bin/env python3
"""Prepare private VPS-only panel files; never change Reddit Compass or start services.

Run as an operator with root access on the target host. Certificate renewal remains
owned by rc-caddy. --refresh-certificate copies only its matching leaf/key after
verification; restart only benka-hermes-panel-caddy-1 afterwards when changed.
No credentials, hostnames or certificate contents are printed.
"""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess


ROOT = Path("/opt/benka-hermes/panel-rehearsal")


def command(*args, stdin=None):
    result = subprocess.run(args, input=stdin, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Panel preparation subprocess failed (output withheld)")
    return result.stdout


def write(path, text, uid=0):
    path.write_text(text)
    os.chmod(path, 0o600)
    os.chown(path, uid, uid)


def directory(path, uid=0):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    os.chown(path, uid, uid)


def certificate_source():
    data = json.loads(command("docker", "inspect", "rc-caddy"))[0]
    if not data["State"]["Running"]:
        raise RuntimeError("Reddit Compass Caddy is not running")
    env = dict(item.split("=", 1) for item in data["Config"]["Env"] if "=" in item)
    host = env.get("RC_PUBLIC_HOST", "")
    if not re.fullmatch(r"[a-z0-9.-]+\.sslip\.io", host):
        raise RuntimeError("Expected the reviewed Reddit Compass sslip.io hostname")
    mounts = [m for m in data["Mounts"] if m["Destination"] == "/data"
              and m["Type"] == "volume" and m.get("Name") == "reddit-compass_caddy_data"]
    if len(mounts) != 1:
        raise RuntimeError("Unexpected source certificate volume")
    root = Path(mounts[0]["Source"]) / "caddy/certificates"
    pairs = [(p, p.with_suffix(".key")) for p in root.glob("*/" + host + "/" + host + ".crt")]
    pairs = [(crt, key) for crt, key in pairs if key.is_file()]
    if len(pairs) != 1:
        raise RuntimeError("Expected one matching certificate/key pair")
    crt, key = pairs[0]
    match = command("openssl", "x509", "-in", str(crt), "-noout", "-checkhost", host)
    if b"does match certificate" not in match:
        raise RuntimeError("Certificate hostname mismatch")
    command("openssl", "x509", "-in", str(crt), "-noout", "-checkend", str(7 * 86400))
    public = command("openssl", "x509", "-in", str(crt), "-pubkey", "-noout")
    if public != command("openssl", "pkey", "-in", str(key), "-pubout"):
        raise RuntimeError("Certificate and key mismatch")
    return host, crt, key


def refresh(host, crt, key):
    tls = ROOT / "private/tls"
    config = json.loads((ROOT / "private/access.json").read_text())
    if config["host"] != host:
        raise RuntimeError("Source hostname changed; review before replacing certificate")
    changed = any(not (tls / name).exists() or (tls / name).read_bytes() != source.read_bytes()
                  for name, source in (("server.crt", crt), ("server.key", key)))
    if changed:
        for name, source in (("server.crt", crt), ("server.key", key)):
            temp = tls / (name + ".new")
            shutil.copyfile(source, temp)
            os.chmod(temp, 0o600)
            os.replace(temp, tls / name)
    print(json.dumps({"certificate_changed": changed, "source_modified": False}))


def prepare():
    if os.geteuid() != 0:
        raise PermissionError("Run this operator script with sudo on the VPS")
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--refresh-certificate", action="store_true")
    action.add_argument("--trust-panel-proxy", action="store_true")
    args = parser.parse_args()
    if args.trust_panel_proxy:
        network = json.loads(command("docker", "network", "inspect", "benka-hermes-panel_panel"))[0]
        if not network["Internal"] or network.get("Labels", {}).get("com.docker.compose.project") != "benka-hermes-panel":
            raise RuntimeError("Expected the isolated Benka panel network")
        subnets = [str(ipaddress.ip_network(item["Subnet"])) for item in network["IPAM"]["Config"]]
        if not subnets or any(ipaddress.ip_network(item).prefixlen == 0 for item in subnets):
            raise RuntimeError("Refusing unbounded proxy trust")
        path = ROOT / "private/state/hermes/config.yaml"
        # Hermes may rewrite JSON-compatible YAML through its settings UI.
        # Parse YAML with the pinned container dependency, never install it on the host.
        program = ("import json\nfrom pathlib import Path\nimport yaml\n"
                   "p=Path('/run/benka/config.yaml')\nc=yaml.safe_load(p.read_text())\n"
                   "c.setdefault('dashboard', {})['trusted_proxies']=" + repr(subnets) + "\n"
                   "p.write_text(yaml.safe_dump(c, allow_unicode=True))\n")
        command("docker", "run", "--rm", "-i", "--network", "none", "--read-only",
                "--tmpfs", "/tmp:size=32m", "--memory", "256m", "--cpus", "1", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--mount",
                "type=bind,src=" + str(path) + ",dst=/run/benka/config.yaml",
                "--entrypoint", "python", "benka-hermes:candidate", "-", stdin=program.encode())
        print(json.dumps({"bounded_panel_proxy_trust": True, "restart_dashboard_required": True}))
        return
    host, crt, key = certificate_source()
    marker = ROOT / "private/access.json"
    if args.refresh_certificate:
        refresh(host, crt, key)
        return
    if marker.exists():
        raise FileExistsError("Panel already prepared; use the explicit certificate refresh operation")
    for path in (ROOT, ROOT / "private", ROOT / "private/tls", ROOT / "private/client"):
        directory(path)
    for path in (ROOT / "private/state", ROOT / "private/state/hermes", ROOT / "private/vault"):
        directory(path, 1000)
    password = secrets.token_urlsafe(32)
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    password_hash = "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(derived).decode()
    config = {
        "timezone": "Europe/Moscow", "toolsets": [], "platform_toolsets": {"cli": [], "telegram": []},
        "agent": {"disabled_toolsets": ["terminal", "file", "browser", "code_execution", "delegation", "cronjob", "kanban"]},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "database": {"journal_mode": "delete"}, "telegram": {"enabled": False},
        "plugins": {"enabled": ["basic"]},
        "dashboard": {"basic_auth": {"username": "benka-admin", "password_hash": password_hash,
                                       "secret": secrets.token_hex(32)}}}
    write(ROOT / "private/state/hermes/config.yaml", json.dumps(config, indent=2), 1000)
    write(ROOT / "private/state/hermes/SOUL.md", "Изолированная репетиция Беньки. Рабочие данные, модели, бот и расписания не подключены.\n", 1000)
    manifest = {"schema": 1, "mode": "rehearsal", "domain": "sandbox", "data_class": "test",
                "production_connections": False, "enabled_operations": ["dashboard"],
                "delivery_targets": [], "jobs": {}, "vault_root": "/vault"}
    write(ROOT / "private/dashboard-manifest.json", json.dumps(manifest, indent=2), 1000)
    write(ROOT / "private/panel.env", "BENKA_PANEL_HOST=" + host + "\n")
    write(marker, json.dumps({"host": host, "url": "https://" + host + ":8451/",
                             "username": "benka-admin", "password": password,
                             "status": "MIGRATION_IN_PROGRESS", "production_connections": False}, indent=2))
    client = ROOT / "private/client"
    command("openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "365",
            "-subj", "/CN=Benka rehearsal client CA", "-keyout", str(client / "ca.key"),
            "-out", str(ROOT / "private/tls/client-ca.crt"), "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    command("openssl", "req", "-new", "-newkey", "rsa:3072", "-nodes", "-subj", "/CN=Benka rehearsal operator",
            "-keyout", str(client / "client.key"), "-out", str(client / "client.csr"))
    write(client / "extensions", "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n")
    command("openssl", "x509", "-req", "-in", str(client / "client.csr"), "-CA", str(ROOT / "private/tls/client-ca.crt"),
            "-CAkey", str(client / "ca.key"), "-CAcreateserial", "-days", "90", "-extfile", str(client / "extensions"),
            "-out", str(client / "client.crt"))
    write(client / "p12-password", secrets.token_urlsafe(24))
    command("openssl", "pkcs12", "-export", "-inkey", str(client / "client.key"), "-in", str(client / "client.crt"),
            "-certfile", str(ROOT / "private/tls/client-ca.crt"), "-out", str(client / "benka-operator.p12"),
            "-passout", "file:" + str(client / "p12-password"))
    for path in client.iterdir():
        os.chmod(path, 0o600)
    refresh(host, crt, key)
    print(json.dumps({"prepared": True, "port": 8451, "started": False, "production_connections": False}))


if __name__ == "__main__":
    prepare()
