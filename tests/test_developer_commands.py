"""Reset/target guards without requiring Docker or reading real env files."""

import copy
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def local_stack(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("local_stack")
    monkeypatch.setattr(module, "LOCAL", tmp_path / "local")
    stack = module.LocalStack("test")
    stack.env_file = tmp_path / "test.env"
    stack.init()
    return module, stack


def resolved_config(stack):
    values = stack.values()
    labels = {"io.commerce.environment": "test", "io.commerce.workspace": values["WORKSPACE_ID"]}

    def ports(mapping):
        return [
            {"host_ip": "127.0.0.1", "target": target, "published": port}
            for target, port in mapping.items()
        ]

    return {
        "name": stack.project,
        "services": {
            "postgres": {
                "image": "postgres:16",
                "labels": labels,
                "ports": ports({5432: values["TEST_POSTGRES_PORT"]}),
                "environment": {
                    "POSTGRES_DB": "commerce_test",
                    "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": values["TEST_POSTGRES_PASSWORD"],
                },
                "volumes": [{"type": "volume", "source": "postgres_test"}],
            },
            "rabbitmq": {
                "image": "rabbitmq:4-management-alpine",
                "labels": labels,
                "ports": ports(
                    {5672: values["LOCAL_BROKER_PORT"], 15672: values["LOCAL_MANAGEMENT_PORT"]}
                ),
                "environment": {
                    "RABBITMQ_DEFAULT_USER": "commerce_test",
                    "RABBITMQ_DEFAULT_VHOST": "commerce_test",
                    "RABBITMQ_DEFAULT_PASS": values["LOCAL_BROKER_PASSWORD"],
                },
                "volumes": [{"type": "volume", "source": "rabbitmq_test"}],
            },
        },
        "volumes": {
            key: {"name": f"{stack.project}_{key}"} for key in ("postgres_test", "rabbitmq_test")
        },
    }


@pytest.mark.parametrize(
    "mutation", ["database", "remote", "port", "volume", "external", "driver", "label", "service"]
)
def test_reset_rejects_other_targets(local_stack, mutation):
    _, stack = local_stack
    config = resolved_config(stack)
    stack.guard_test_config(config)
    bad = copy.deepcopy(config)
    pg = bad["services"]["postgres"]
    if mutation == "database":
        pg["environment"]["POSTGRES_DB"] = "postgres"
    elif mutation == "remote":
        pg["ports"][0]["host_ip"] = "0.0.0.0"
    elif mutation == "port":
        pg["ports"][0]["published"] = "5432"
    elif mutation == "volume":
        pg["volumes"][0] = {"type": "bind", "source": "D:/shared-data"}
    elif mutation == "external":
        bad["volumes"]["postgres_test"]["external"] = True
    elif mutation == "driver":
        bad["volumes"]["postgres_test"]["driver"] = "remote-driver"
    elif mutation == "label":
        pg["labels"]["io.commerce.environment"] = "dev"
    else:
        bad["services"]["unrelated"] = {}
    with pytest.raises(ValueError):
        stack.guard_test_config(bad)


def test_reset_requires_apply_and_cannot_select_dev(local_stack):
    module, stack = local_stack
    with pytest.raises(ValueError):
        stack.manage("reset")
    with pytest.raises(ValueError):
        module.LocalStack("dev").manage("reset", apply=True)


def test_container_labels_alone_do_not_allow_another_port(local_stack):
    _, stack = local_stack
    info = {
        "Config": {
            "Labels": {
                "com.docker.compose.service": "postgres",
                "com.docker.compose.project": stack.project,
                "io.commerce.environment": "test",
                "io.commerce.workspace": stack.values()["WORKSPACE_ID"],
            }
        },
        "HostConfig": {
            "PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "59999"}]}
        },
        "State": {"Running": True},
    }
    with pytest.raises(ValueError):
        stack.guard_container(info, require_running=True)


def test_test_urls_ignore_ambient_dev_settings(local_stack, monkeypatch):
    _, stack = local_stack
    monkeypatch.setenv("DATABASE_URL", "postgresql://private@remote.example/postgres")
    monkeypatch.setenv("DB_SSL_CA_FILE", "D:/private/ca.crt")
    monkeypatch.setenv("BOOTSTRAP_DATABASE_URL", "do-not-inherit")
    monkeypatch.setenv("db_ssl_ca_file", "do-not-inherit-lowercase")
    env = stack.test_env("order-service")
    assert env["APP_ENV"] == "test"
    assert "@127.0.0.1:" in env["DATABASE_URL"]
    assert env["DATABASE_URL"].endswith("/commerce_test")
    assert env["BROKER_URL"].endswith("/commerce_test")
    assert "BOOTSTRAP_DATABASE_URL" not in env and "DB_SSL_CA_FILE" not in env
    assert "db_ssl_ca_file" not in env


def test_container_env_excludes_migration_and_bootstrap_credentials(
    local_stack, monkeypatch, tmp_path
):
    module, _ = local_stack
    monkeypatch.setattr(module, "ROOT", tmp_path)
    path = tmp_path / "apps/order-service/.env"
    path.parent.mkdir(parents=True)
    path.write_text(
        "DATABASE_ENABLED=false\nMIGRATION_DATABASE_URL=do-not-copy\n"
        "migration_database_url=do-not-copy\nBOOTSTRAP_DATABASE_URL=do-not-copy\n"
    )
    stack = module.LocalStack("dev")
    stack.env_file = tmp_path / "dev.env"
    stack.init()
    stack.write_apps_env(offline=False)
    content = (module.LOCAL / "apps/order-service.env").read_text()
    assert "do-not-copy" not in content
    assert "@rabbitmq:5672/commerce_dev" in content
    stack.write_apps_env(offline=True)
    assert "DATABASE_URL" not in (module.LOCAL / "apps/order-service.env").read_text()
