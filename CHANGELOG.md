# Changelog

## Unreleased

- Added Windows/Python 3.11 and 3.12 public-baseline CI, wheel inspection, and
  tracked-file privacy checks.
- Added repository governance templates, monthly dependency updates, and a
  manual Hancom 2022 release gate.
- Documented the safe-mode and experimental foreground connection paths.

## 0.3.0rc1 — public-release candidate

- Renamed the distributable package and MCP server to `hwp-live-safe`.
- Added portable MCP configuration examples and excluded machine-specific
  configurations from source control.
- Added a public MIT license, security policy, and explicit limitations.
- Renamed the default local profile folder to `HWP Live Safe`; the older
  environment variable and existing default folder are accepted for migration.
- Reduced the chance that unexpected local worker output is returned through
  an MCP error message.
