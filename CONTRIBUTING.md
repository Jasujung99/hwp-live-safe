# Contributing

Thank you for helping improve HWP Live Safe. Keep changes narrow, reviewable,
and safe for people who may have sensitive documents open.

## Before opening a pull request

1. Create a branch from the current `main` branch.
2. Do not commit real HWP/HWPX/PDF files, local MCP configurations, profile
   values, tokens, machine paths, certificates, or screenshots containing
   personal data.
3. Keep runtime changes separate from documentation or release-governance
   changes when practical.
4. Run the public baseline locally:

   ```powershell
   uv sync --extra dev --locked
   $env:PYTHONDONTWRITEBYTECODE = "1"
   uv run python -m pytest -p no:cacheprovider
   uv run python tests/mcp_smoke.py
   uv run python scripts/check_public_repo.py
   uv build
   uv run python scripts/check_wheel.py
   ```

The unit and fake-MCP checks must not start Hancom. Run the optional real
Hancom test only on a disposable session and follow
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

## Pull requests

Describe the user-visible behavior, safety impact, tests performed, and any
remaining limitation. A pull request must pass CI and resolve its review
conversations before merge. The repository uses squash merge for small changes.

Security vulnerabilities and reports containing sensitive information must use
[private vulnerability reporting](https://github.com/Jasujung99/hwp-live-safe/security/advisories/new),
not a public issue.
