"""Start isolated local HTTP services and verify Next.js rewrite against a real gateway.

Run from the repo: uv run --locked --all-packages python scripts/smoke_web.py
No database, broker, migrations or dev credentials are used.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request(
    url: str, headers: dict[str, str] | None = None
) -> tuple[int, Message[str, str], bytes]:
    try:
        with urlopen(Request(url, headers=headers or {}), timeout=30) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def wait_ready(url: str, process: subprocess.Popen[bytes]) -> None:
    until = time.monotonic() + 90
    while time.monotonic() < until:
        if process.poll() is not None:
            raise RuntimeError("Smoke child process exited before readiness")
        try:
            if request(url)[0] == 200:
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.4)
    raise RuntimeError("Smoke readiness timed out")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            import signal

            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)


def main() -> None:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Node.js is required")
    catalog_port, gateway_port, web_port = free_port(), free_port(), free_port()
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_ENABLED": "false",
        "BROKER_ENABLED": "false",
        "HTTP_HOST": "127.0.0.1",
        "CATALOG_BASE_URL": f"http://127.0.0.1:{catalog_port}",
        "GATEWAY_URL": f"http://127.0.0.1:{gateway_port}",
        "NEXT_TELEMETRY_DISABLED": "1",
    }
    children: list[subprocess.Popen[bytes]] = []
    with tempfile.TemporaryFile() as logs:

        def launch(command: list[str], cwd: Path, extra: dict[str, str]) -> subprocess.Popen[bytes]:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env={**env, **extra},
                stdout=logs,
                stderr=logs,
                start_new_session=os.name != "nt",
            )
            children.append(process)
            return process

        try:
            catalog = launch(
                [sys.executable, "-m", "commerce_catalog"], ROOT, {"HTTP_PORT": str(catalog_port)}
            )
            wait_ready(f"http://127.0.0.1:{catalog_port}/health/live", catalog)
            gateway = launch(
                [sys.executable, str(ROOT / "tests/fixtures/web_gateway.py")],
                ROOT,
                {"HTTP_PORT": str(gateway_port)},
            )
            wait_ready(f"http://127.0.0.1:{gateway_port}/health/live", gateway)
            web = launch(
                [
                    node,
                    str(ROOT / "apps/web/node_modules/next/dist/bin/next"),
                    "dev",
                    "--webpack",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                ],
                ROOT / "apps/web",
                {},
            )
            base = f"http://127.0.0.1:{web_port}"
            wait_ready(base, web)
            status, _, page = request(base)
            assert status == 200 and "Kiểm tra kết nối hệ thống" in page.decode()
            request_id = str(uuid4())
            status, headers, body = request(
                base + "/api/v1/health/catalog", {"X-Request-Id": request_id}
            )
            assert status == 200 and json.loads(body)["service"] == "catalog-service"
            assert headers.get("X-Request-Id") == request_id
            status, headers, body = request(
                base + "/api/v1/__smoke/echo?value=forwarded",
                {
                    "X-Request-Id": request_id,
                    "Cookie": "smoke=local-only",
                    "Authorization": "Bearer smoke-only",
                },
            )
            assert status == 200
            assert json.loads(body) == {
                "cookie": "local-only",
                "authorization": "Bearer smoke-only",
                "requestId": request_id,
                "query": "forwarded",
            }
            assert "smoke_reply=ok" in headers.get("Set-Cookie", "")
            stop(catalog)
            status, _, body = request(base + "/api/v1/health/catalog")
            assert status == 503 and json.loads(body)["code"] == "UPSTREAM_UNAVAILABLE"
            stop(gateway)
            assert request(base + "/api/v1/health/catalog")[0] >= 500
            print(
                "PASS: page, real Catalog/gateway chain, cookie/header/query forwarding, "
                "Set-Cookie, Catalog/gateway outages"
            )
        except BaseException:
            logs.seek(0)
            print(logs.read().decode(errors="replace")[-12000:], file=sys.stderr)
            raise
        finally:
            for child in reversed(children):
                stop(child)


if __name__ == "__main__":
    main()
