# Changelog

## Unreleased

- Added Windows/Python 3.11 and 3.12 public-baseline CI, wheel inspection, and
  tracked-file privacy checks.
- Added repository governance templates, monthly dependency updates, and a
  manual Hancom 2022 release gate.
- Documented the safe-mode and experimental foreground connection paths.

## 0.3.0rc1 — GitHub pre-release `v0.3.0-rc.1` (2026-09-02)

- Recorded the scoped real-Hancom 2022 gate: native safe-mode creation,
  reviewed text/table insertion, dummy-profile privacy, stale-preview refusal,
  safe Undo, and one user-approved experimental foreground insertion.
- Fixed foreground HWND comparison on Python 3.12 by comparing native handle
  values rather than ctypes wrapper identity.
- Fixed the 64-bit Win32 `INPUT` layout used by foreground typing so
  `SendInput` receives the required 40-byte native structure size.

- Renamed the distributable package and MCP server to `hwp-live-safe`.
- Added portable MCP configuration examples and excluded machine-specific
  configurations from source control.
- Added a public MIT license, security policy, and explicit limitations.
- Renamed the default local profile folder to `HWP Live Safe`; the older
  environment variable and existing default folder are accepted for migration.
- Reduced the chance that unexpected local worker output is returned through
  an MCP error message.
