# Release checklist

This checklist gates tags and GitHub releases. `0.3.0rc1` remains a source
pre-release candidate until every required automated and manual item is
recorded without personal data.

## Recorded public baseline — 2026-09-01

- The [Windows public-baseline run](https://github.com/Jasujung99/hwp-live-safe/actions/runs/33445910351)
  passed on Python 3.11 and 3.12.
- A clean local rerun passed 22 tests, the 15-tool fake MCP smoke, the 39-file
  public-repository scan, package build, and wheel/sdist inspection.
- Host preflight found Windows build `22621.4317`, Hancom executable version
  `12.0.0.850`, Python `3.12.13`, MCP `2.1.1`, a registered HWP COM class, and
  a ready 32-bit worker.
- With pre-existing Hancom windows open, `hwp_start_new_document` refused
  before COM creation and the window list remained unchanged. This verifies
  the fail-closed guard; it is not a substitute for the manual gate below.

## Automated baseline

- [x] Windows CI passes on Python 3.11 and 3.12.
- [x] Unit tests pass with bytecode and pytest cache creation disabled.
- [x] The fake stdio MCP smoke test discovers exactly 15 tools and reports the
      `hwp-live-safe` server identity.
- [x] The wheel contains the PowerShell COM worker and the
      `hwp-live-safe = hwp_live.server:main` entry point.
- [x] The public-repository scan finds no tracked local configuration, profile
      values, personal Windows paths, private keys, or recognizable tokens.

## Manual Hancom Office 2022 gate

Close every important Hancom window first. Use only a new blank document and a
profile containing dummy values. Do not save the generated document.

- [ ] Record Windows edition/build, Hancom Office/Hancom 2022 build, Python
      version, MCP client/version, and installation method.
- [ ] `hwp_start_new_document` creates one new visible unsaved document and
      does not attach to a pre-existing document.
- [ ] Text preview/apply/read-back works for size, bold, and alignment.
- [ ] A non-empty table preview/apply/read-back works within documented limits.
- [ ] A dummy profile field is absent from list/preview responses and appears
      only after approved insertion.
- [ ] Manual document text change makes an older preview stale.
- [ ] Immediate Undo succeeds for the latest unchanged safe edit; Undo refuses
      after a manual change.
- [ ] Experimental foreground mode lists and selects only the user-confirmed
      Hancom window, inserts one short literal string at a collapsed caret, and
      is disconnected immediately afterward.
- [ ] No open, save, export, close, delete, or arbitrary-action capability is
      exposed by the MCP tool list.

## Release decision

- [x] Update `KNOWN_LIMITATIONS.md` with every failed or unverified observation.
- [ ] Record the verified environment in the HWP AI Bridge compatibility table.
- [x] Confirm private vulnerability reporting and `main` branch protection are
      enabled on GitHub.
- [x] Confirm the source version is consistent in `pyproject.toml`, `hwp_live`,
      MCP initialization, and the changelog.
- [ ] Confirm the final `v0.3.0-rc.1` release notes match the verified manual
      observations.
- [ ] Create `v0.3.0-rc.1` as a GitHub pre-release only after this gate passes.
- [x] Do not publish to PyPI during the initial source/Release phase.
