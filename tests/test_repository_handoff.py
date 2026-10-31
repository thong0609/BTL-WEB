"""Prevent the handoff check from reading or echoing accidental credential files."""

import importlib.util
from pathlib import Path


def load_checker():
    path = Path(__file__).resolve().parents[1] / "scripts/check_repository.py"
    spec = importlib.util.spec_from_file_location("handoff_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secret_file_is_rejected_without_reading(monkeypatch, tmp_path):
    checker = load_checker()

    def must_not_read(*args, **kwargs):
        raise AssertionError("Secret file must not be opened")

    monkeypatch.setattr(Path, "read_text", must_not_read)
    errors = checker.check_file(tmp_path / ".env.bootstrap", tmp_path)
    assert errors and "must not be tracked" in errors[0]


def test_template_rejects_credentials_without_echoing_them(tmp_path):
    checker = load_checker()
    path = tmp_path / ".env.example"
    path.write_text("DATABASE_URL=private-credential\n", encoding="utf-8")
    errors = checker.check_file(path, tmp_path)
    assert errors and "private-credential" not in " ".join(errors)
    path.write_text("DATABASE_URL=\n# DATABASE_URL=placeholder\n", encoding="utf-8")
    assert checker.check_file(path, tmp_path) == []
