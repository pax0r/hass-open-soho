#!/usr/bin/env python3
"""Exercise the real image, PocketBase migrations and UI using a test Ingress proxy."""

import argparse
import contextlib
import hashlib
import http.client
import io
import json
import zipfile
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlencode

PROXY_IMAGE = (
    "python:3.12.14-slim-bookworm"
    "@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e"
)
UI_HEADER = {"X-OpenSOHO-UI": "1"}
SUPERVISOR_IP = "172.30.32.2"


def docker(*args, env=None):
    result = subprocess.run(["docker", *args], text=True, capture_output=True, env=env)
    if result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def request(endpoint, path, method="GET", body=None, headers=None, expected=200):
    conn = http.client.HTTPConnection(endpoint, timeout=8)
    try:
        conn.request(method, path, body, headers or {})
        response = conn.getresponse()
        result = response.read()
        assert response.status == expected, (
            f"{method} {path.partition('?')[0]} returned {response.status}, expected {expected}"
        )
        return result, dict(response.getheaders())
    finally:
        conn.close()


def published(container, port):
    endpoint = docker("port", container, str(port) + "/tcp")
    assert endpoint.startswith("127.0.0.1:"), endpoint
    return endpoint


def wait_for_controller(agent):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            request(agent, "/controller/register/", "POST", "secret=invalid",
                    {"Content-Type": "application/x-www-form-urlencoded"}, 403)
            return
        except (ConnectionError, http.client.HTTPException):
            time.sleep(0.3)
    raise TimeoutError("OpenWISP listener did not start")


def verify_browser(endpoint, prefix, admin, agent, monitor_path, monitoring, backup_name):
    from playwright.sync_api import sync_playwright

    base = f"http://{endpoint}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_BIN") or None, args=["--no-sandbox"]
        )
        context = browser.new_context()
        context.set_default_timeout(12_000)
        context.add_cookies([{"name": "test_session", "value": admin, "url": base}])
        page = context.new_page()
        failures = []

        def inspect_response(response):
            if response.status >= 400:
                failures.append(f"{response.status} {response.url.partition('?')[0]}")

        page.on("response", inspect_response)
        page.on("pageerror", lambda err: failures.append(str(err)))
        page.goto(base + "/")
        frame = page.frame_locator('iframe[title="OpenSOHO"]')
        frame.locator(".app-header").wait_for()
        frame.get_by_text("Home Assistant", exact=True).wait_for()
        frame.get_by_role("link", name="Dashboard", exact=True).click()
        frame.locator(".page-dashboard").wait_for()
        frame.get_by_role("link", name="Configuration", exact=True).click()
        frame.get_by_text("smoke-router").first.wait_for()
        inner = page.locator('iframe[title="OpenSOHO"]').element_handle().content_frame()
        assert inner is not None
        assert inner.url.startswith(base + prefix + "/_/"), inner.url
        assert inner.evaluate("app.pb.authStore.token") == ""
        assert inner.evaluate("app.pb.baseURL") == base + prefix + "/"
        inner.evaluate("location.reload()")
        frame.get_by_text("smoke-router").first.wait_for()
        assert not failures, failures

        # The dashboard does not subscribe to changes by default. Exercise
        # PocketBase's actual SSE connect, subscribe and delivery via the SDK.
        inner.evaluate("""async () => {
            window.deviceChange = new Promise(resolve => window.resolveDeviceChange = resolve);
            await app.pb.collection('devices').subscribe('*', event => {
                if (event.record.name === 'smoke-router') window.resolveDeviceChange(event.action);
            });
        }""")
        request(agent, monitor_path, "POST", monitoring, {"Content-Type": "application/json"})
        assert inner.evaluate("""Promise.race([
            window.deviceChange,
            new Promise(resolve => setTimeout(() => resolve('timeout'), 7000)),
        ])""") == "update"
        # Changing the IP allowlist previously called the blocked PB auth-refresh.
        await_settings = """async () => {
            await app.pb.settings.update({superuserIPs: ['172.30.32.2']});
            location.hash = '#/settings';
        }"""
        inner.evaluate(await_settings)
        frame.locator(".superuser-accordion summary").click()
        frame.locator("#superuserIPs").fill("")
        frame.get_by_role("button", name="Save changes", exact=True).click()
        frame.get_by_text("Successfully saved application settings.", exact=True).wait_for()
        assert inner.evaluate("app.pb.authStore.isValid")
        assert inner.evaluate("app.pb.authStore.token") == ""

        inner.evaluate("location.hash = '#/settings/backups'")
        frame.get_by_text(backup_name, exact=True).wait_for()
        with page.expect_download() as downloaded:
            frame.get_by_role("button", name="Download", exact=True).click()
        assert downloaded.value.failure() is None
        assert downloaded.value.suggested_filename == backup_name
        assert not failures, failures
        context.clear_cookies()
        assert page.request.get(base + prefix + "/api/ha/session", headers=UI_HEADER).status == 403
        context.add_cookies([{"name": "test_session", "value": admin, "url": base}])
        assert page.request.get(base + prefix + "/api/ha/session", headers=UI_HEADER).status == 200
        browser.close()
    print("PASS Chromium iframe, assets, dashboard API, navigation, reload, SSE and session removal")


def smoke(image, replacement, use_browser):
    name = "opensoho-smoke-" + secrets.token_hex(4)
    controller, proxy = name + "-app", name + "-proxy"
    secret, key, admin, user = (secrets.token_hex(16) for _ in range(4))
    proxy_env = os.environ | {
        "TEST_INGRESS_PATH": secrets.token_urlsafe(24),
        "TEST_ADMIN": admin,
        "TEST_USER": user,
    }
    prefix = "/api/hassio_ingress/" + proxy_env["TEST_INGRESS_PATH"]
    fixture = Path(__file__).with_name("mock_supervisor.py").resolve()
    with tempfile.TemporaryDirectory(prefix="opensoho-smoke-") as data:
        options = Path(data) / "options.json"
        options.touch(mode=0o600)
        options.write_text(json.dumps({"shared_secret": secret, "enable_new_devices": True}))

        def start(image_name):
            docker("run", "-d", "--name", controller, "--network", name,
                   "--network-alias", "controller", "--ip", "172.30.32.3",
                   "--publish", "127.0.0.1::8090", "--publish", "127.0.0.1::8091",
                   "--mount", f"type=volume,src={name},dst=/data",
                   "--mount", f"type=bind,src={options},dst=/data/options.json,readonly",
                   image_name)
            agent = published(controller, 8090)
            wait_for_controller(agent)
            return agent, published(controller, 8091)

        with contextlib.ExitStack() as clean:
            docker("network", "create", "--subnet", "172.30.32.0/23", name)
            clean.callback(lambda: docker("network", "rm", name))
            docker("volume", "create", name)
            clean.callback(lambda: docker("volume", "rm", name))
            clean.callback(lambda: subprocess.run(
                ["docker", "rm", "-f", proxy, controller], capture_output=True
            ))
            try:
                agent, direct = start(image)
                docker("run", "-d", "--name", proxy, "--network", name, "--ip", SUPERVISOR_IP,
                       "--publish", "127.0.0.1::8000",
                       "--env", "TEST_INGRESS_PATH", "--env", "TEST_ADMIN", "--env", "TEST_USER",
                       "--mount", f"type=bind,src={fixture},dst=/proxy.py,readonly",
                       PROXY_IMAGE, "python", "/proxy.py", env=proxy_env)
                ingress = published(proxy, 8000)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        request(ingress, "/")
                        break
                    except (ConnectionError, http.client.HTTPException):
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.2)

                forged_headers = UI_HEADER | {
                    "X-Remote-User-Id": "0123456789abcdef" * 2,
                    "X-Remote-User-Groups": "system-admin",
                    "X-Ingress-Path": prefix,
                }
                request(direct, "/api/ha/session", headers=forged_headers, expected=403)
                request(agent, "/api/ha/session", headers=forged_headers, expected=404)
                request(agent, "/_/", headers=forged_headers, expected=404)
                request(agent, "/api/collections/_superusers/auth-with-password", "POST", expected=404)
                request(agent, "/api/v1/network-overview", headers=forged_headers, expected=404)
                request(ingress, prefix + "/api/ha/session", headers=forged_headers, expected=403)
                user_headers = forged_headers | {"Cookie": "test_session=" + user}
                request(ingress, prefix + "/api/ha/session", headers=user_headers, expected=403)
                admin_headers = UI_HEADER | {"Cookie": "test_session=" + admin}
                result, headers = request(ingress, prefix + "/api/ha/session", headers=admin_headers)
                assert set(json.loads(result)) == {"id", "collectionName"}, "session contains credentials"
                assert "Set-Cookie" not in headers
                _, headers = request(ingress, prefix + "/", headers=admin_headers, expected=307)
                assert headers["Location"] == prefix + "/_/"
                request(ingress, prefix + "/api/health", headers=admin_headers)
                request(ingress, prefix + "/api/v1/network-overview", headers=admin_headers)
                print("PASS trusted admin, rejected other identities, no browser credential, isolated LAN")

                fields = {
                    "name": "smoke-router", "backend": "netjsonconfig.OpenWrt",
                    "secret": secret, "key": key, "mac_address": "02:01:02:03:04:05",
                    "model": "smoke-test", "os": "OpenWrt 25.12", "system": "test",
                }
                encoded = urlencode(fields)
                form = {"Content-Type": "application/x-www-form-urlencoded"}
                request(agent, "/controller/register/", "POST",
                        urlencode(fields | {"secret": secrets.token_hex(16)}), form, 403)
                registration, _ = request(agent, "/controller/register/", "POST", encoded, form, 201)
                lines = dict(line.split(": ", 1) for line in registration.decode().splitlines() if ": " in line)
                uuid = lines["uuid"]
                assert lines["is-new"] == "1"
                checksum_path = f"/controller/checksum/{uuid}/?key={key}"
                download_path = f"/controller/download-config/{uuid}/?key={key}"
                monitor_endpoint = f"/api/v1/monitoring/device/{uuid}/"
                monitor_path = f"{monitor_endpoint}?key={key}"
                monitoring = json.dumps({
                    "type": "DeviceMonitoring", "interfaces": [],
                    "general": {"local_time": int(time.time()), "uptime": 42},
                })
                checksum, _ = request(agent, checksum_path)
                archive, _ = request(agent, download_path)
                assert hashlib.md5(archive, usedforsecurity=False).hexdigest().encode() == checksum
                with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
                    assert "etc/config/openwisp-monitoring" in bundle.getnames(), bundle.getnames()
                json_headers = {"Content-Type": "application/json"}
                request(agent, monitor_endpoint, "POST", monitoring, json_headers, 403)
                request(agent, f"{monitor_endpoint}?key={secrets.token_hex(16)}",
                        "POST", monitoring, json_headers, 403)
                request(agent, monitor_path, "POST", monitoring, json_headers)
                request(ingress, prefix + monitor_endpoint, "POST", monitoring,
                        admin_headers | json_headers, 404)
                devices_path = prefix + "/api/collections/devices/records"
                result, _ = request(ingress, devices_path, headers=admin_headers)
                record = json.loads(result)["items"][0]
                assert record["name"] == "smoke-router" and record["health_status"] == "healthy"
                request(agent, f"/api/v1/monitoring/device/?key={key}&current=true",
                        "POST", monitoring, json_headers)
                file_path = prefix + f"/api/files/{record['collectionId']}/{record['id']}/{record['config']}"
                panel_archive, _ = request(ingress, file_path, headers=admin_headers)
                assert panel_archive == archive
                print("PASS registration, incorrect secret rejection, checksum, config archive and monitoring")

                backup_name = "smoke-backup.zip"
                request(ingress, prefix + "/api/backups", "POST",
                        json.dumps({"name": backup_name}),
                        admin_headers | {"Content-Type": "application/json"}, 204)
                for attempt in range(40):
                    result, _ = request(ingress, prefix + "/api/backups", headers=admin_headers)
                    if any(item["key"] == backup_name for item in json.loads(result)):
                        break
                    time.sleep(0.25)
                else:
                    raise TimeoutError("PocketBase backup was not created")
                backup_path = prefix + "/api/backups/" + backup_name
                backup, _ = request(ingress, backup_path, headers=admin_headers)
                with zipfile.ZipFile(io.BytesIO(backup)) as bundle:
                    assert "data.db" in bundle.namelist()
                request(ingress, backup_path, headers=user_headers, expected=403)
                request(agent, "/api/backups/" + backup_name, expected=404)
                print("PASS backup download through Ingress and rejected unauthorized downloads")

                if use_browser:
                    verify_browser(ingress, prefix, admin, agent, monitor_path, monitoring, backup_name)
                else:
                    print("SKIP Chromium (run without --http-only to execute it)")

                docker("stop", "--timeout", "8", controller)
                assert docker("inspect", "-f", "{{.State.ExitCode}}", controller) == "0"
                logs = subprocess.check_output(
                    ["docker", "logs", controller], text=True, stderr=subprocess.STDOUT
                )
                assert all(value not in logs for value in (key, secret, admin)), "secret in container logs"
                assert "numradios" not in logs, "raw upstream configuration output reached the add-on log"
                assert "OpenWISP listener ready" in logs, "add-on startup diagnostics are missing"
                docker("rm", controller)
                agent, _ = start(replacement or image)
                result, _ = request(ingress, devices_path, headers=admin_headers)
                assert json.loads(result)["items"][0]["id"] == record["id"]
                after, _ = request(agent, download_path)
                assert after, "device configuration unavailable after container replacement"
                print("PASS graceful SIGTERM and persistent data after "
                      + ("image change" if replacement else "container replacement"))
            except BaseException:
                subprocess.run(["docker", "logs", "--tail", "30", controller], check=False)
                raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="hass-open-soho:local")
    parser.add_argument("--replacement-image", help="optional second image for an upgrade test")
    parser.add_argument("--http-only", action="store_true")
    args = parser.parse_args()
    smoke(args.image, args.replacement_image, not args.http_only)
