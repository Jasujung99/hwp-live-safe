from __future__ import annotations

import os
import tomllib
from pathlib import Path

from hwp_live import __version__
from hwp_live.profile import ProfileStore
from hwp_live.server import _run


ROOT = Path(__file__).resolve().parents[1]


def test_public_distribution_metadata_matches_runtime_version() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    assert project["name"] == "hwp-live-safe"
    assert project["version"] == __version__
    assert project["scripts"]["hwp-live-safe"] == "hwp_live.server:main"


def test_public_config_examples_are_portable() -> None:
    example = (ROOT / ".mcp.json.example").read_text(encoding="utf-8")
    codex_example = (ROOT / ".codex" / "config.toml.example").read_text(encoding="utf-8")
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert '"command": "hwp-live-safe"' in example
    assert 'command = "hwp-live-safe"' in codex_example
    assert "D:\\" not in example
    assert "C:\\" not in example
    assert ".mcp.json" in ignored
    assert ".codex/config.toml" in ignored


def test_new_profile_environment_name_takes_precedence(monkeypatch, tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"
    monkeypatch.setenv("HWP_LIVE_PROFILE_DIR", os.fspath(legacy))
    monkeypatch.setenv("HWP_LIVE_SAFE_PROFILE_DIR", os.fspath(current))

    assert ProfileStore.default_profile_dir() == current


def test_default_profile_folder_uses_public_product_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HWP_LIVE_SAFE_PROFILE_DIR", raising=False)
    monkeypatch.delenv("HWP_LIVE_PROFILE_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", os.fspath(tmp_path))

    assert ProfileStore.default_profile_dir() == tmp_path / "HWP Live Safe" / "profiles"


def test_legacy_default_profile_folder_is_used_only_when_new_folder_is_absent(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HWP_LIVE_SAFE_PROFILE_DIR", raising=False)
    monkeypatch.delenv("HWP_LIVE_PROFILE_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", os.fspath(tmp_path))
    legacy = tmp_path / "HWP Live 2022" / "profiles"
    legacy.mkdir(parents=True)

    assert ProfileStore.default_profile_dir() == legacy


def test_unexpected_error_does_not_echo_local_exception_text() -> None:
    def fail() -> None:
        raise RuntimeError("private diagnostic text")

    response = _run("result", fail)

    assert response["ok"] is False
    assert response["error"]["code"] == "UNEXPECTED_ERROR"
    assert "private diagnostic text" not in response["error"]["message"]
