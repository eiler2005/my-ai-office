#!/usr/bin/env python3
"""Run operator smoke checks on the VPS; print no hosts, cookies or credentials."""
import base64
import http.client
import json
import os
from pathlib import Path
import socket
import ssl


ROOT = Path("/opt/benka-hermes/panel-rehearsal/private")


def main():
    access = json.loads((ROOT / "access.json").read_text())
    host, port = access["host"], 8451
    context = ssl.create_default_context()
    context.load_cert_chain(ROOT / "client/client.crt", ROOT / "client/client.key")
    results = {}

    def request(path, *, method="GET", body=None, cookie="", client=context):
        connection = http.client.HTTPSConnection(host, port, context=client, timeout=20)
        headers = {"Origin": "https://" + host + ":8451", "Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        status, raw, response_headers = response.status, response.read(), response.getheaders()
        connection.close()
        return status, raw, response_headers

    try:
        request("/", client=ssl.create_default_context())
    except ssl.SSLError:
        results["mtls_denies_missing_certificate"] = True
    else:
        raise AssertionError("Missing client certificate was accepted")
    status, _, _ = request("/api/config")
    assert status == 401, "Unauthenticated API must be denied"
    results["native_auth_denies_missing_session"] = True
    status, _, _ = request("/auth/password-login", method="POST", body={
        "provider": "basic", "username": access["username"], "password": "incorrect-fixture-value"})
    assert status == 401, "Incorrect password must be denied"
    results["native_auth_denies_wrong_password"] = True
    status, raw, headers = request("/auth/password-login", method="POST", body={
        "provider": "basic", "username": access["username"], "password": access["password"]})
    assert status == 200 and json.loads(raw)["ok"], "Login failed"
    cookie_headers = [v for k, v in headers if k.lower() == "set-cookie" and "max-age=0" not in v.lower()]
    assert cookie_headers and all("secure" in v.lower() and "httponly" in v.lower() for v in cookie_headers), "Session cookies must be Secure and HttpOnly"
    cookie = "; ".join(v.split(";", 1)[0] for v in cookie_headers)
    results["native_login_secure_cookie"] = True
    for path, name in (("/", "dashboard_html"), ("/api/config", "settings_api"), ("/api/sessions", "sessions_api")):
        status, raw, _ = request(path, cookie=cookie)
        assert status == 200, name + " failed"
        if name == "dashboard_html":
            assert b"<html" in raw.lower(), "Dashboard build is missing"
        results[name] = True

    def upgrade(ticket=""):
        key = base64.b64encode(os.urandom(16)).decode()
        headers = ["GET /api/ws HTTP/1.1", "Host: " + host + ":8451", "Upgrade: websocket",
                   "Connection: Upgrade", "Sec-WebSocket-Key: " + key, "Sec-WebSocket-Version: 13",
                   "Origin: https://" + host + ":8451"]
        if ticket:
            headers.append("Sec-WebSocket-Protocol: hermes-gateway-v1, hermes-gateway-ticket." + ticket)
        with socket.create_connection((host, port), timeout=20) as plain:
            with context.wrap_socket(plain, server_hostname=host) as connection:
                connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode())
                raw = b""
                while b"\r\n\r\n" not in raw and len(raw) < 16384:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    raw += chunk
                return int(raw.split(b" ", 2)[1])

    assert upgrade() == 403, "Unauthenticated WebSocket accepted"
    results["websocket_denies_missing_ticket"] = True
    status, raw, _ = request("/api/auth/ws-ticket", method="POST", cookie=cookie)
    assert status == 200, "WebSocket ticket failed"
    ticket = json.loads(raw)["ticket"]
    assert upgrade(ticket) == 101, "WebSocket upgrade failed"
    assert upgrade(ticket) == 403, "WebSocket ticket replay accepted"
    results["websocket_upgrade_and_replay_denial"] = True
    report = {"checks": results, "production_connections": False, "model_chat_tested": False}
    report_file = ROOT.parent / "verification.json"
    report_file.write_text(json.dumps(report, indent=2))
    os.chmod(report_file, 0o600)
    print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Full HTTP/SSL exceptions can include the private hostname or credentials.
        print(json.dumps({"passed": False, "error_type": type(error).__name__,
                          "check": str(error) if isinstance(error, AssertionError) else "transport_or_setup"}))
        raise SystemExit(1)
