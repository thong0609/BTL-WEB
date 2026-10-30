"""Developer commands; all paths are resolved from this file, not the caller's cwd."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from local_stack import MESSAGING, ROOT, SERVICES, LocalStack, clean_test_env


def execute(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def npm(action: str) -> None:
    binary = shutil.which("npm")
    if not binary:
        raise ValueError("npm is not available on PATH")
    execute([binary, "run", action], cwd=ROOT / "apps/web")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("run", "worker"):
        cmd = commands.add_parser(action)
        choices = [*SERVICES, "web"] if action == "run" else sorted(MESSAGING)
        cmd.add_argument("service", choices=choices)
        cmd.add_argument("--broker", choices=["local", "configured"], default="local")
        cmd.add_argument("--test-stack", action="store_true")
        if action == "worker":
            cmd.add_argument("--once", action="store_true")
    for action in ("lint", "typecheck", "test", "build"):
        cmd = commands.add_parser(action)
        cmd.add_argument("service", choices=[*SERVICES, "web", "backend", "all"])
        if action == "test":
            cmd.add_argument("--integration", action="store_true")
    cmd = commands.add_parser("infra")
    cmd.add_argument("mode", choices=["dev", "test"])
    cmd.add_argument(
        "operation",
        choices=[
            "init",
            "up",
            "down",
            "status",
            "prepare",
            "reset",
            "apps-up",
            "apps-down",
            "apps-build",
        ],
    )
    cmd.add_argument("--apply", action="store_true")
    cmd.add_argument("--offline", action="store_true")
    cmd = commands.add_parser("broker")
    cmd.add_argument("operation", choices=["check", "topology", "smoke"])
    cmd.add_argument("service", choices=sorted(MESSAGING))
    cmd.add_argument("--broker", choices=["local", "configured"], default="local")
    cmd.add_argument("--test-stack", action="store_true")
    cmd.add_argument("--apply", action="store_true")
    commands.add_parser("smoke-web")
    args = parser.parse_args()
    try:
        python = sys.executable
        if args.action == "infra":
            LocalStack(args.mode).manage(args.operation, apply=args.apply, offline=args.offline)
        elif args.action in {"run", "worker", "broker"}:
            service = args.service
            if service == "web":
                if args.test_stack:
                    raise ValueError("Use smoke-web to check an isolated frontend/backend chain")
                npm("dev")
                return 0
            env = os.environ.copy()
            if args.test_stack:
                stack = LocalStack("test")
                stack.guard_existing_test_resources(require_running=True)
                env = stack.test_env(service)
            elif service in MESSAGING and args.broker == "local":
                env.update(LocalStack("dev").broker_env())
                env.pop("BROKER_SSL_CA_FILE", None)
            if args.action == "broker":
                command = [
                    python,
                    str(ROOT / "scripts/broker.py"),
                    args.operation,
                    "--service",
                    service,
                ]
                if args.apply:
                    command.append("--apply")
            else:
                module = SERVICES[service]
                command = [python, "-m", module]
                if args.action == "worker":
                    command = [python, "-m", f"{module}.worker", "--run"]
                    if args.once:
                        command.append("--once")
            execute(command, env=env)
        elif args.action == "smoke-web":
            execute([python, str(ROOT / "scripts/smoke_web.py")], env=clean_test_env())
        else:
            service = args.service
            if service != "web":
                roots = (
                    ["apps", "packages", "scripts", "tests"]
                    if service
                    in {
                        "all",
                        "backend",
                    }
                    else [f"apps/{service}"]
                )
                if args.action == "lint":
                    execute([python, "-m", "ruff", "check", *roots])
                    execute([python, "-m", "ruff", "format", "--check", *roots])
                elif args.action == "typecheck":
                    paths = [] if service in {"all", "backend"} else [f"apps/{service}/src"]
                    execute([python, "-m", "mypy", *paths])
                elif args.action == "test":
                    print("Backend base tests cover shared contracts across services", flush=True)
                    flags = ["--run-postgres", "--run-rabbitmq"] if args.integration else []
                    execute([python, "-m", "pytest", "-q", *flags], env=clean_test_env())
                elif args.action == "build":
                    targets = list(SERVICES) if service in {"all", "backend"} else [service]
                    for target in targets:
                        execute(
                            [
                                "docker",
                                "build",
                                "-f",
                                f"apps/{target}/Dockerfile",
                                "-t",
                                f"commerce-{target}:dev",
                                ".",
                            ]
                        )
            if service in {"web", "all"}:
                npm(args.action)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Command failed ({type(exc).__name__}); check local setup and the step 6 guide")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
