"""Repository-scoped Docker Compose stacks. Never administer the shared dev database."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "infra/.local"
WORKSPACE = hashlib.sha256(os.path.normcase(str(ROOT)).encode()).hexdigest()[:10]
SERVICES = {
    "api-gateway": "commerce_gateway",
    "identity-service": "commerce_identity",
    "catalog-service": "commerce_catalog",
    "inventory-service": "commerce_inventory",
    "order-service": "commerce_order",
    "payment-service": "commerce_payment",
}
MESSAGING = {"inventory-service", "order-service", "payment-service"}


def clean_test_env() -> dict[str, str]:
    """Do not inherit credential-bearing settings from a developer shell."""
    blocked = ("DATABASE_", "MIGRATION_", "DB_", "BROKER_", "BOOTSTRAP_", "SUPABASE_")
    names = {
        "SERVICE_NAME",
        "HTTP_PORT",
        "HTTP_HOST",
        "CATALOG_BASE_URL",
        "CORS_ORIGINS",
        "HTTP_TIMEOUT_SECONDS",
        "HTTP_MAX_CONNECTIONS",
        "TEST_ADMIN_DATABASE_URL",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(blocked) and key.upper() not in names
    }
    return {**env, "APP_ENV": "test", "DATABASE_ENABLED": "false", "BROKER_ENABLED": "false"}


def write_env(path: Path, values: dict[str, str]) -> None:
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Multiline environment values are not supported")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


def checked(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


class LocalStack:
    def __init__(self, mode: str):
        if mode not in {"dev", "test"}:
            raise ValueError("Only local dev/test stacks are supported")
        self.mode = mode
        self.project = f"commerce-{mode}-{WORKSPACE}"
        self.file = ROOT / f"infra/compose.{mode}.yaml"
        self.env_file = LOCAL / f"{mode}.env"

    def init(self) -> None:
        if self.env_file.exists():
            self.values()  # Validate, never rotate credentials under existing volumes.
            print(f"Existing {self.mode} settings retained: infra/.local/{self.mode}.env")
            return
        write_env(
            self.env_file,
            {
                "WORKSPACE_ID": WORKSPACE,
                "LOCAL_BROKER_PASSWORD": secrets.token_hex(24),
                "LOCAL_BROKER_PORT": "5672" if self.mode == "dev" else "5673",
                "LOCAL_MANAGEMENT_PORT": "15672" if self.mode == "dev" else "15673",
                "TEST_POSTGRES_PASSWORD": secrets.token_hex(24),
                "TEST_POSTGRES_PORT": "55432",
            },
        )
        (LOCAL / "certs").mkdir(parents=True, exist_ok=True)
        write_env(LOCAL / f"{self.mode}-broker.host.env", self.broker_env())
        print(f"Created ignored local settings: infra/.local/{self.mode}.env")
        print("Credentials are in the local files only; no service .env has been changed")

    def values(self) -> dict[str, str]:
        if not self.env_file.is_file():
            raise ValueError(f"Run infra {self.mode} init first")
        values = dict(dotenv_values(self.env_file, interpolate=False))
        keys = {
            "WORKSPACE_ID",
            "LOCAL_BROKER_PASSWORD",
            "LOCAL_BROKER_PORT",
            "LOCAL_MANAGEMENT_PORT",
            "TEST_POSTGRES_PASSWORD",
            "TEST_POSTGRES_PORT",
        }
        if set(values) != keys or values["WORKSPACE_ID"] != WORKSPACE:
            raise ValueError("Unexpected local configuration keys or workspace")
        for key in ("LOCAL_BROKER_PASSWORD", "TEST_POSTGRES_PASSWORD"):
            if not re.fullmatch(r"[a-f0-9]{48}", values[key] or ""):
                raise ValueError("Retain the generated hexadecimal local passwords")
        ports = [
            int(values[key] or "0")
            for key in (
                "LOCAL_BROKER_PORT",
                "LOCAL_MANAGEMENT_PORT",
                "TEST_POSTGRES_PORT",
            )
        ]
        if any(not 1024 <= port <= 65535 for port in ports) or len(set(ports)) != 3:
            raise ValueError("Local ports must be distinct numbers from 1024 to 65535")
        return {key: str(value) for key, value in values.items()}

    def process_env(self) -> dict[str, str]:
        # Explicit values beat ambient Compose interpolation; no implicit root .env.
        env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
        return {**env, **self.values()}

    def command(self, *args: str, apps: bool = False) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(ROOT / "infra"),
            "--env-file",
            str(self.env_file),
            "--file",
            str(self.file),
        ]
        if apps:
            command += ["--profile", "apps"]
        return [*command, *args]

    def compose(self, *args: str, apps: bool = False) -> None:
        checked(self.command(*args, apps=apps), env=self.process_env())

    def config(self) -> dict:
        output = subprocess.check_output(
            self.command("config", "--format", "json", apps=True),
            cwd=ROOT,
            env=self.process_env(),
            stderr=subprocess.PIPE,
        )
        return json.loads(output)

    def guard_test_config(self, config: dict) -> None:
        """Allowlist endpoints AND resource shapes before any test data deletion."""
        if self.mode != "test" or config.get("name") != self.project:
            raise ValueError("Only this repository's test project can be reset")
        services = config.get("services", {})
        if set(services) != {"postgres", "rabbitmq"}:
            raise ValueError("Test stack may contain only PostgreSQL and RabbitMQ")
        values = self.values()
        expected = {
            "postgres": ("postgres:16", {5432: values["TEST_POSTGRES_PORT"]}, "postgres_test"),
            "rabbitmq": (
                "rabbitmq:4-management-alpine",
                {5672: values["LOCAL_BROKER_PORT"], 15672: values["LOCAL_MANAGEMENT_PORT"]},
                "rabbitmq_test",
            ),
        }
        for name, (image, ports, volume) in expected.items():
            service = services[name]
            if service.get("image") != image or any(
                service.get(key)
                for key in (
                    "command",
                    "entrypoint",
                    "network_mode",
                    "privileged",
                    "build",
                    "env_file",
                )
            ):
                raise ValueError("Unexpected test service image or execution settings")
            labels = service.get("labels", {})
            if (
                labels.get("io.commerce.environment") != "test"
                or labels.get("io.commerce.workspace") != WORKSPACE
            ):
                raise ValueError("Test ownership labels do not match")
            actual = service.get("ports", [])
            if len(actual) != len(ports) or any(
                item.get("host_ip") != "127.0.0.1"
                or str(item.get("published")) != ports.get(item.get("target"))
                for item in actual
            ):
                raise ValueError("Test endpoints must match the allowlisted loopback ports")
            mounts = service.get("volumes", [])
            if (
                len(mounts) != 1
                or mounts[0].get("type") != "volume"
                or mounts[0].get("source") != volume
            ):
                raise ValueError("Test stack cannot mount external/bind storage")
        pg = services["postgres"]["environment"]
        broker = services["rabbitmq"]["environment"]
        if pg.get("POSTGRES_DB") != "commerce_test" or pg.get("POSTGRES_USER") != "postgres":
            raise ValueError("Only database commerce_test is allowed")
        if (
            pg.get("POSTGRES_PASSWORD") != values["TEST_POSTGRES_PASSWORD"]
            or broker.get("RABBITMQ_DEFAULT_PASS") != values["LOCAL_BROKER_PASSWORD"]
        ):
            raise ValueError("Test credentials differ from the local test configuration")
        if any(
            broker.get(key) != "commerce_test"
            for key in (
                "RABBITMQ_DEFAULT_USER",
                "RABBITMQ_DEFAULT_VHOST",
            )
        ):
            raise ValueError("Only the commerce_test broker user/vhost is allowed")
        volumes = config.get("volumes", {})
        if set(volumes) != {"postgres_test", "rabbitmq_test"}:
            raise ValueError("Unexpected test volumes")
        for key, volume in volumes.items():
            if (
                volume.get("driver", "local") != "local"
                or volume.get("external")
                or volume.get("driver_opts")
                or volume.get("name") != f"{self.project}_{key}"
            ):
                raise ValueError("Test volumes must belong to this Compose project")

    def guard_existing_test_resources(self, *, require_running: bool = False) -> None:
        """Do not trust APP_ENV or the Compose file to identify existing resources."""
        self.guard_test_config(self.config())
        ids = subprocess.check_output(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
            ],
            text=True,
        ).split()
        found = set()
        for container in ids:
            info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
            found.add(self.guard_container(info, require_running=require_running))
        if require_running and found != {"postgres", "rabbitmq"}:
            raise ValueError("Start both verified test services before connecting")
        for key in ("postgres_test", "rabbitmq_test"):
            result = subprocess.run(
                ["docker", "volume", "inspect", f"{self.project}_{key}"],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                self.guard_labels(json.loads(result.stdout)[0].get("Labels", {}))

    def guard_container(self, info: dict, *, require_running: bool) -> str:
        labels = info["Config"].get("Labels", {})
        service = labels.get("com.docker.compose.service")
        if service not in {"postgres", "rabbitmq"}:
            raise ValueError("Unexpected container in the test project")
        self.guard_labels(labels)
        values = self.values()
        ports = (
            {"5432/tcp": values["TEST_POSTGRES_PORT"]}
            if service == "postgres"
            else {
                "5672/tcp": values["LOCAL_BROKER_PORT"],
                "15672/tcp": values["LOCAL_MANAGEMENT_PORT"],
            }
        )
        expected = {
            key: [{"HostIp": "127.0.0.1", "HostPort": value}] for key, value in ports.items()
        }
        if info["HostConfig"].get("PortBindings") != expected:
            raise ValueError("Existing container ports differ from the allowlisted test endpoints")
        if require_running and not info["State"]["Running"]:
            raise ValueError("Test containers must be running before connecting")
        return service

    def guard_labels(self, labels: dict) -> None:
        if any(
            labels.get(key) != value
            for key, value in {
                "com.docker.compose.project": self.project,
                "io.commerce.environment": "test",
                "io.commerce.workspace": WORKSPACE,
            }.items()
        ):
            raise ValueError("Existing resource does not belong to this workspace's test stack")

    def broker_env(self, *, container: bool = False) -> dict[str, str]:
        values = self.values()
        user = "commerce_dev" if self.mode == "dev" else "commerce_test"
        host = "rabbitmq:5672" if container else f"127.0.0.1:{values['LOCAL_BROKER_PORT']}"
        return {
            "BROKER_ENABLED": "true",
            "BROKER_URL": f"amqp://{user}:{values['LOCAL_BROKER_PASSWORD']}@{host}/{user}",
        }

    def test_env(self, service: str | None = None) -> dict[str, str]:
        if self.mode != "test":
            raise ValueError("Test URLs cannot be generated for dev")
        from commerce_backend_common.database import DATABASE_SPECS

        values = self.values()
        host = f"127.0.0.1:{values['TEST_POSTGRES_PORT']}/commerce_test"
        password = values["TEST_POSTGRES_PASSWORD"]
        env = {
            **clean_test_env(),
            **self.broker_env(),
            "DB_SSL_MODE": "disable",
            "TEST_ADMIN_DATABASE_URL": f"postgresql+asyncpg://postgres:{password}@{host}",
        }
        for spec in DATABASE_SPECS:
            for role in (spec.runtime, spec.migrator):
                env[f"{role.upper()}_PASSWORD"] = password
            if service == spec.service:
                env.update(
                    {
                        "DATABASE_ENABLED": "true",
                        "DB_SCHEMA": spec.schema,
                        "DATABASE_URL": f"postgresql+asyncpg://{spec.runtime}:{password}@{host}",
                        "MIGRATION_DATABASE_URL": f"postgresql+asyncpg://{spec.migrator}:{password}@{host}",
                    }
                )
        if service not in MESSAGING:
            env["BROKER_ENABLED"] = "false"
        return env

    def prepare_test(self) -> None:
        self.guard_existing_test_resources(require_running=True)
        from commerce_backend_common.database import DATABASE_SPECS

        python = [sys.executable, str(ROOT / "scripts/database.py")]
        checked([*python, "bootstrap", "--target", "test", "--apply"], env=self.test_env())
        for spec in DATABASE_SPECS:
            env = self.test_env(spec.service)
            checked([*python, "upgrade", "--service", spec.service, "--apply"], env=env)
            checked([*python, "inspect", "--service", spec.service], env=env)
        for service in sorted(MESSAGING):
            checked(
                [
                    sys.executable,
                    str(ROOT / "scripts/broker.py"),
                    "topology",
                    "--service",
                    service,
                    "--apply",
                ],
                env=self.test_env(service),
            )
        checked(
            [
                sys.executable,
                str(ROOT / "scripts/broker.py"),
                "smoke",
                "--service",
                "order-service",
                "--apply",
            ],
            env=self.test_env("order-service"),
        )
        print("Test stack prepared: five baseline schemas/permissions and broker topology verified")

    def write_apps_env(self, *, offline: bool) -> None:
        if self.mode != "dev":
            raise ValueError("Application containers use the dev Compose project")
        (LOCAL / "certs").mkdir(parents=True, exist_ok=True)
        for service, module in SERVICES.items():
            values = {"APP_ENV": "dev", "DATABASE_ENABLED": "false", "BROKER_ENABLED": "false"}
            if not offline:
                source = {
                    key.upper(): value
                    for key, value in dotenv_values(
                        ROOT / f"apps/{service}/.env", interpolate=False
                    ).items()
                }
                # Runtime fields only. Do not copy migration/bootstrap credentials into images.
                cls = importlib.import_module(f"{module}.settings").Settings
                for key, value in source.items():
                    if (
                        key.lower() in cls.model_fields
                        and value is not None
                        and key
                        not in {
                            "MIGRATION_DATABASE_URL",
                            "BROKER_URL",
                            "BROKER_SSL_CA_FILE",
                            "SERVICE_NAME",
                            "APP_ENV",
                            "HTTP_HOST",
                            "HTTP_PORT",
                            "DB_SSL_CA_FILE",
                        }
                    ):
                        values[key] = value
                ca = source.get("DB_SSL_CA_FILE")
                if ca and values["DATABASE_ENABLED"].lower() in {"true", "1", "yes", "on"}:
                    ca_path = Path(ca).expanduser()
                    if not ca_path.is_absolute():
                        ca_path = ROOT / ca_path
                    shutil.copyfile(ca_path, LOCAL / f"certs/{service}.crt")
                    values["DB_SSL_CA_FILE"] = f"/run/commerce-certs/{service}.crt"
            if service in MESSAGING:
                values.update(self.broker_env(container=True))
            write_env(LOCAL / f"apps/{service}.env", values)

    def manage(self, action: str, *, apply: bool = False, offline: bool = False) -> None:
        if action == "reset" and (self.mode != "test" or not apply):
            raise ValueError("Only infra test reset --apply can delete test data")
        if action == "init":
            self.init()
            return
        self.values()
        if self.mode == "test":
            self.guard_existing_test_resources()
        if action == "reset":
            self.compose("down", "--volumes")
            self.compose("up", "--detach", "--wait", "--wait-timeout", "150")
            print("Reset only the verified local test project; run infra test prepare next")
        elif action == "prepare":
            if self.mode != "test":
                raise ValueError("Preparing a dev database is outside this script")
            self.prepare_test()
        elif action == "up":
            services = ["rabbitmq"] if self.mode == "dev" else ["postgres", "rabbitmq"]
            self.compose("up", "--detach", "--wait", "--wait-timeout", "150", *services)
        elif action == "down":
            self.compose("down", apps=self.mode == "dev")  # Volumes retained.
        elif action == "status":
            self.compose("ps", "--all", apps=self.mode == "dev")
        elif action in {"apps-up", "apps-build"} and self.mode == "dev":
            self.write_apps_env(offline=offline)
            self.compose("build", apps=True)
            if action == "apps-up":
                self.compose("up", "--detach", "--wait", "--wait-timeout", "150", apps=True)
        elif action == "apps-down" and self.mode == "dev":
            self.compose("stop", *SERVICES, "web", apps=True)
        else:
            raise ValueError("Unsupported stack action")
