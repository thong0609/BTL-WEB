"""Check handoff files without opening ignored local secrets or printing their contents."""

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_KEY = re.compile(
    r"PASSWORD|SECRET|TOKEN|(?:DATABASE|BROKER)_URL|(?:PRIVATE|SERVICE_ROLE)_KEY"
)


def is_template(path: Path) -> bool:
    return path.name.endswith(".env.example") or (
        path.name.startswith(".env.") and path.name.endswith(".example")
    )


def check_file(path: Path, root: Path = ROOT) -> list[str]:
    relative = path.relative_to(root)
    name = relative.as_posix()
    # Reject paths before reading: diagnostics only contain filenames/line numbers.
    if (
        any(part in {".local", ".venv", "node_modules", "certs"} for part in relative.parts)
        or path.suffix.lower() in {".pem", ".key", ".crt", ".p12", ".pfx"}
        or (".env" in path.name and not is_template(path))
    ):
        return [f"{name}: local environment, certificate or dependency file must not be tracked"]
    if not path.is_file():  # Tracked deletion in the worktree.
        return []
    if path.suffix != ".md" and not is_template(path):
        return []
    content = path.read_text(encoding="utf-8")
    errors = []
    if is_template(path):
        for number, line in enumerate(content.splitlines(), start=1):
            if line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if SENSITIVE_KEY.search(key.upper()) and value.strip().strip("\"'"):
                errors.append(f"{name}:{number}: credential fields must be empty in env templates")
    if path.suffix == ".md":
        if content.count("```") % 2:
            errors.append(f"{name}: unclosed Markdown code fence")
        prose = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
        for target in re.findall(r"\]\(([^)]+)\)", prose):
            target = target.strip("<>").split("#", 1)[0]
            if not target or ":" in target:
                continue
            if not (path.parent / unquote(target)).exists():
                errors.append(f"{name}: broken local Markdown link")
    return errors


def main() -> int:
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode("utf-8")
        .split("\0")
    )
    errors = [error for name in set(names) if name for error in check_file(ROOT / name)]
    for error in sorted(errors):
        print(error)
    if errors:
        return 1
    print("PASS: repository paths, empty credential fields and local Markdown links/fences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
