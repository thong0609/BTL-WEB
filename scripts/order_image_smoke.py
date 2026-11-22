"""Check the built Order API image and restart it without dev credentials.

Run after docker build -f apps/order-service/Dockerfile -t commerce-order-service:step16 .
This checks image startup only. Database, broker and business flows have separate tests.
"""

import argparse
import json
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import uuid4


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, timeout=60).strip()


def ready(base: str) -> None:
    until = time.monotonic() + 40
    while time.monotonic() < until:
        try:
            with urlopen(base + "/health/ready", timeout=2) as response:
                body = json.load(response)
                assert response.status == 200
                assert body["checks"]["database"] == "disabled"
                assert body["checks"]["broker"] == "disabled"
                return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    raise RuntimeError("Order image readiness timed out")


def web_smoke(image: str) -> None:
    name = "commerce-order-web-test-" + uuid4().hex[:12]
    try:
        docker("run", "--detach", "--name", name, "--publish", "127.0.0.1::3100", image)
        for attempt in range(2):
            base = "http://127.0.0.1:" + docker("port", name, "3100/tcp").rsplit(":", 1)[1]
            until = time.monotonic() + 40
            while True:
                try:
                    with urlopen(base + "/checkout", timeout=2) as response:
                        assert response.status == 200
                        assert "Đăng nhập để tiếp tục" in response.read().decode()
                    break
                except (URLError, TimeoutError, ConnectionError):
                    if time.monotonic() >= until:
                        raise RuntimeError("Web image startup timed out") from None
                    time.sleep(0.25)
            for path in ("/orders", "/admin/orders"):
                with urlopen(base + path, timeout=5) as response:
                    assert response.status == 200
                    assert "Đăng nhập để tiếp tục" in response.read().decode()
            if attempt == 0:
                docker("restart", name)
        assert docker("inspect", "--format", "{{.Config.User}}", name) == "node"
        print("PASS: non-root standalone web image, Order pages, restart (no login bypass)")
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="commerce-order-service:step16")
    parser.add_argument("--web-image", help="Also check the built frontend standalone image")
    args = parser.parse_args()
    name = "commerce-order-image-test-" + uuid4().hex[:12]
    try:
        docker(
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            "127.0.0.1::3004",
            "--env",
            "APP_ENV=test",
            "--env",
            "DATABASE_ENABLED=false",
            "--env",
            "BROKER_ENABLED=false",
            args.image,
        )
        binding = docker("port", name, "3004/tcp")
        base = "http://127.0.0.1:" + binding.rsplit(":", 1)[1]
        ready(base)
        user = docker("inspect", "--format", "{{.Config.User}}", name)
        command = json.loads(docker("inspect", "--format", "{{json .Config.Cmd}}", name))
        assert user == "appuser" and command == ["/opt/venv/bin/python", "-m", "commerce_order"]
        try:
            urlopen(base + "/api/v1/orders", timeout=5)
            raise AssertionError("Unauthenticated Order access must fail closed")
        except HTTPError as error:
            assert error.code == 401
        docker("restart", name)
        # Docker may allocate a different ephemeral host port on restart.
        base = "http://127.0.0.1:" + docker("port", name, "3004/tcp").rsplit(":", 1)[1]
        ready(base)
        with urlopen(base + "/health/live", timeout=5) as response:
            assert response.status == 200
        print(
            "PASS: non-root Order image, API-only entrypoint, 401 without auth, restart/readiness"
        )
        print("Scope: database/broker disabled; no dev env, migrations or business worker started")
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=30, check=False
        )
    if args.web_image:
        web_smoke(args.web_image)


if __name__ == "__main__":
    main()
