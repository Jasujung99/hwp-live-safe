# HWP Live Safe

> **Pre-release candidate (`0.3.0rc1`)** — a local, preview-first MCP server for a new visible Hancom Office 2022 document on Windows.

HWP Live Safe gives MCP-compatible assistants a deliberately narrow way to draft a document without silently touching an arbitrary user file. It opens a new unsaved Hancom document that it owns, reads its current text, makes a short-lived preview, and applies only the approved preview.

It is intended for careful drafting, personal-form entry, and reviewable insertions. It is **not** an editor for arbitrary existing `.hwp`/`.hwpx` files.

## What it does

- Starts one visible, new, unsaved Hancom Office 2022 document.
- Inserts one reviewed text block or one non-empty table per preview.
- Supports text size, bold, and paragraph alignment for native text insertion.
- Detects a changed document text fingerprint and discards stale previews.
- Allows an immediate, verified undo of its own latest unchanged edit.
- Reads local profile values without returning those values in profile-list or profile-preview MCP responses.
- Offers a tightly restricted **experimental** foreground typing mode for one user-selected Hancom window and one short, approved insertion.

## What it deliberately does not do

- Open, save, save-as, export, close, delete, or overwrite a user file.
- Natively attach to, read, or edit an already-open normal Hancom document.
- Replace a selection, bulk-fill a form, or make unreviewed long-form edits.
- Run an HTTP server or call an LLM, analytics service, or cloud API itself.

Read [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) before using it with an important document.

## Requirements

- Windows
- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- Hancom Office 2022 with the 32-bit `HWPFrame.HwpObject` automation registration available

The native safe mode refuses to start while a Hancom window is already open; this prevents accidental attachment to a user document. The experimental foreground mode is separate and does not provide native document attachment.

## Install from a source checkout

This release candidate is prepared for a public repository; it is not claimed to be a published package registry release yet.

```powershell
uv sync --extra dev
```

For a persistent command available to an MCP client, install the checkout as a uv tool:

```powershell
uv tool install .
```

The installed command is `hwp-live-safe`.

When a registry release exists, the equivalent installation will be `uv tool install hwp-live-safe`.

## Connect an MCP client

After installing the command, use a stdio MCP configuration equivalent to [.mcp.json.example](.mcp.json.example):

```json
{
  "mcpServers": {
    "hwp-live-safe": {
      "command": "hwp-live-safe",
      "args": []
    }
  }
}
```

For Codex, copy the relevant values from [.codex/config.toml.example](.codex/config.toml.example) into the user or project configuration after installing the command. The same stdio command can be used by Claude Code, Cursor, Grok Build, and other MCP-compatible local clients.

Do not commit a real `.mcp.json` or `.codex/config.toml`: they can contain machine-specific paths or client credentials and are ignored by default.

## Safe workflow

1. Ask the assistant to call `hwp_start_new_document`.
2. It calls `hwp_read_context` and uses the returned `revision`.
3. It calls `hwp_preview_edits` with one concise text block or table.
4. For a long, ambiguous, or replacement-style change, inspect the preview and explicitly approve it before `hwp_apply_preview`.
5. Read the document again after manual changes. A manual change invalidates prior previews and safe undo.

For example:

> Start a new HWP Live Safe document. Make a centered bold heading “2026 지원서”, then show me the preview for a two-column personal-information table. Do not save anything.

## Local profile values

Copy `profiles/profile.example.json` to the local profile directory and fill only its `value` fields:

```powershell
$profileDir = Join-Path $env:LOCALAPPDATA "HWP Live Safe\profiles"
New-Item -ItemType Directory -Force $profileDir
Copy-Item .\profiles\profile.example.json (Join-Path $profileDir "default.json")
```

Alternatively, set `HWP_LIVE_SAFE_PROFILE_DIR` to a local directory. The older `HWP_LIVE_PROFILE_DIR` name remains accepted for migration from the pre-release project name. If the new default folder does not exist but the old `%LOCALAPPDATA%\HWP Live 2022\profiles` folder does, the server reads that old folder until you migrate it.

Use `hwp_profile_list`, then `hwp_preview_profile_insert`. The list and preview return only the field label and configured state, not the value. Once inserted, the value is part of the document; later `hwp_read_context` calls can therefore return it to the MCP client. Choose a trusted client and model provider before reading a sensitive document.

Never commit a real profile file.

## Experimental existing-window typing

The `hwp_foreground_*` tools are intentionally much narrower than the native safe mode. They can list visible Hancom window titles, let the user explicitly select one, and type one approved short text at a user-confirmed collapsed caret. They cannot read the document, inspect selection state, replace text, create tables, or undo automatically.

Use this only for a short literal insertion and verify the visible result in Hancom immediately. For a mistake, use Hancom's own Undo. Do not use it for long prose, selected-range replacement, batch edits, or sensitive work that needs reliable read-back.

## Development and verification

The unit tests use an in-memory Hancom substitute and never start Hancom:

```powershell
uv sync --extra dev
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.venv\Scripts\python.exe tests\mcp_smoke.py
```

`tests/mcp_live_smoke.py` is an optional real Hancom smoke test. Run it only on a disposable session with no Hancom window open; it creates an unsaved document, inserts test text and a table, verifies them, and undoes them.

## Security and privacy

See [SECURITY.md](SECURITY.md). HWP Live Safe itself uses local stdio and does not make network calls. Your MCP client may still send tool results or document text to a model provider, so the end-to-end privacy boundary depends on the client and provider you choose.

## License and trademark notice

This project is released under the [MIT License](LICENSE). It is an independent open-source project and is not affiliated with or endorsed by Hancom.
