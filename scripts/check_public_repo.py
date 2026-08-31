"""Fail when public source control contains local configuration or secrets."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def public_candidate_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def check_paths(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    forbidden_exact = {
        ".codex/config.toml",
        ".claude/settings.local.json",
        ".cursor/mcp.json",
        ".gemini/settings.json",
        ".grok/config.toml",
        ".mcp.json",
        "profile.local.json",
    }
    private_suffixes = {".key", ".p12", ".pem", ".pfx"}

    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        lowered = relative.lower()
        if lowered in forbidden_exact:
            errors.append(f"tracked local configuration: {relative}")
        if path.name == ".env" or (
            path.name.startswith(".env.") and path.name != ".env.example"
        ):
            errors.append(f"tracked environment file: {relative}")
        if path.suffix.lower() in private_suffixes:
            errors.append(f"tracked key or certificate container: {relative}")
        if lowered.startswith(("credentials/", "secrets/")):
            errors.append(f"tracked secret directory entry: {relative}")
        if lowered.startswith("profiles/") and lowered != "profiles/profile.example.json":
            errors.append(f"tracked non-example profile: {relative}")
    return errors


def check_contents(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    patterns = {
        "personal Windows user path": re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+[^<>{}\s\\/]+"),
        "Windows desktop machine name": re.compile(r"\bDESKTOP-[A-Z0-9]{6,}\b"),
        "GitHub token": re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b"),
        "OpenAI-style API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
        "xAI API key": re.compile(r"\bxai-[A-Za-z0-9_-]{20,}\b"),
        "AWS access key": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    }
    private_key_header = "-----BEGIN " + "PRIVATE KEY-----"
    text_suffixes = {
        "",
        ".json",
        ".md",
        ".ps1",
        ".py",
        ".toml",
        ".txt",
        ".yml",
        ".yaml",
    }

    for path in paths:
        if path.suffix.lower() not in text_suffixes or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if private_key_header in content:
            errors.append(f"private key header: {relative}")
        for label, pattern in patterns.items():
            if pattern.search(content):
                errors.append(f"{label}: {relative}")
    return errors


def check_examples_and_ignores() -> list[str]:
    errors: list[str] = []
    mcp_example = json.loads((ROOT / ".mcp.json.example").read_text(encoding="utf-8"))
    server = mcp_example.get("mcpServers", {}).get("hwp-live-safe", {})
    if server.get("command") != "hwp-live-safe":
        errors.append(".mcp.json.example does not use the public CLI identity")

    with (ROOT / ".codex" / "config.toml.example").open("rb") as handle:
        codex_example = tomllib.load(handle)
    codex_server = codex_example.get("mcp_servers", {}).get("hwp_live_safe", {})
    if codex_server.get("command") != "hwp-live-safe":
        errors.append(".codex/config.toml.example does not use the public CLI identity")

    profile = json.loads(
        (ROOT / "profiles" / "profile.example.json").read_text(encoding="utf-8")
    )
    for key, field in profile.get("fields", {}).items():
        if field.get("value") is not None:
            errors.append(f"profile example contains a configured value: {key}")

    ignore_lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_ignores = {
        ".codex/config.toml",
        ".claude/settings.local.json",
        ".cursor/mcp.json",
        ".gemini/settings.json",
        ".grok/config.toml",
        ".mcp.json",
        "*.key",
        "*.p12",
        "*.pem",
        "*.pfx",
        "profiles/*.json",
    }
    for missing in sorted(required_ignores - ignore_lines):
        errors.append(f"missing .gitignore rule: {missing}")
    return errors


def main() -> int:
    paths = public_candidate_files()
    errors = check_paths(paths) + check_contents(paths) + check_examples_and_ignores()
    if errors:
        print("Public repository check failed:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Public repository check passed ({len(paths)} public candidate files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
