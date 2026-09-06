import shlex
import subprocess
from pathlib import Path

import config as config_mod


def test_ensure_env_file_does_not_overwrite_existing(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    env_path.write_text("BAILIAN_API_KEY=keep-me\n", encoding="utf-8")
    example_path.write_text("BAILIAN_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "ENV_PATH", env_path)
    monkeypatch.setattr(config_mod, "ENV_EXAMPLE_PATH", example_path)
    config_mod.ensure_env_file()
    assert env_path.read_text(encoding="utf-8") == "BAILIAN_API_KEY=keep-me\n"


def test_ensure_env_file_creates_when_missing(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text("BAILIAN_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "ENV_PATH", env_path)
    monkeypatch.setattr(config_mod, "ENV_EXAMPLE_PATH", example_path)
    config_mod.ensure_env_file()
    assert env_path.read_text(encoding="utf-8") == "BAILIAN_API_KEY=\n"


def test_ensure_venv_protects_env_appends_once(tmp_path, monkeypatch):
    activate = tmp_path / "activate"
    activate.write_text("export VIRTUAL_ENV=dummy\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "ACTIVATE_PATH", activate)
    config_mod.ensure_venv_protects_env()
    config_mod.ensure_venv_protects_env()
    text = activate.read_text(encoding="utf-8")
    assert text.count(config_mod.PROTECT_ENV_MARKER) == 1
    assert "protect_env.sh" in text


def test_protect_env_skips_existing_env(tmp_path):
    script = Path(__file__).resolve().parents[1] / "protect_env.sh"
    (tmp_path / ".env").write_text("BAILIAN_API_KEY=keep-me\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("BAILIAN_API_KEY=\n", encoding="utf-8")
    result = subprocess.run(
        ["zsh", "-c", f"source {shlex.quote(str(script))} && cp .env.example .env"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "skip overwrite" in result.stderr
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "BAILIAN_API_KEY=keep-me\n"


def test_protect_env_copies_when_env_missing(tmp_path):
    script = Path(__file__).resolve().parents[1] / "protect_env.sh"
    (tmp_path / ".env.example").write_text("BAILIAN_API_KEY=\n", encoding="utf-8")
    subprocess.run(
        ["zsh", "-c", f"source {shlex.quote(str(script))} && cp .env.example .env"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "BAILIAN_API_KEY=\n"
