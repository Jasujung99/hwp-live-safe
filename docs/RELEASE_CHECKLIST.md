# Release checklist

This checklist gates tags and GitHub releases. `0.3.0rc1` remains a source
pre-release candidate until every required automated and manual item is
recorded without personal data.

## Recorded public baseline — 2026-09-02

- The [Windows public-baseline run](https://github.com/Jasujung99/hwp-live-safe/actions/runs/33445910351)
  passed on Python 3.11 and 3.12.
- A clean local rerun passed 27 tests, the 15-tool fake MCP smoke, the 39-file
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

## Manual Hancom Office 2022 gate — 2026-09-02

The gate used a new blank unsaved document and dummy profile values. No
existing Hancom window was open when native safe mode started, and the
generated document was not saved. Native safe mode was witnessed at
`72cda61`. The later runtime changes `514477c` and `0436e9a` are confined to
the experimental foreground backend and its tests; the foreground item below
was re-witnessed at `0436e9a`.

| Item | Recorded value |
|---|---|
| Windows | Windows 10 Home 22H2, build `22621.4317` |
| Hancom Office 2022 executable | `12.0.0.850` |
| Python | `3.12.13` |
| MCP Python SDK | `2.1.1` |
| MCP client | Codex CLI `0.147.0` |
| Installation | Local source checkout; no PyPI package used |
| Automation | Registered 32-bit `HWPFrame.HwpObject` worker |
| Runtime source evidence | Native safe mode `72cda61`; foreground `0436e9a` |

- [x] `hwp_start_new_document` created one new visible unsaved document and did
      not attach to a pre-existing document.
- [x] Text preview, apply, and read-back worked for size, bold, and alignment.
- [x] A non-empty table preview, apply, and read-back worked within documented
      limits.
- [x] A dummy profile field was absent from list/preview responses and appeared
      only after approved insertion.
- [x] A manual document-text change made an older preview stale.
- [x] Immediate Undo succeeded for the latest unchanged safe edit; Undo refused
      after a manual change.
- [x] Experimental foreground mode listed and selected only the user-confirmed
      disposable Hancom window, inserted `FG-GATE-01` at a collapsed caret, and
      disconnected immediately afterward.
- [x] The MCP tool list exposed no open, save, export, close, delete, or
      arbitrary-action capability.

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
