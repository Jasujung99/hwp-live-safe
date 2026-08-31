# Release checklist

This checklist gates tags and GitHub releases. `0.3.0rc1` remains a source
pre-release candidate until every required automated and manual item is
recorded without personal data.

## Automated baseline

- [ ] Windows CI passes on Python 3.11 and 3.12.
- [ ] Unit tests pass with bytecode and pytest cache creation disabled.
- [ ] The fake stdio MCP smoke test discovers exactly 15 tools and reports the
      `hwp-live-safe` server identity.
- [ ] The wheel contains the PowerShell COM worker and the
      `hwp-live-safe = hwp_live.server:main` entry point.
- [ ] The public-repository scan finds no tracked local configuration, profile
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

- [ ] Update `KNOWN_LIMITATIONS.md` with every failed or unverified observation.
- [ ] Record the verified environment in the HWP AI Bridge compatibility table.
- [ ] Confirm private vulnerability reporting and `main` branch protection are
      enabled on GitHub.
- [ ] Confirm the version is consistent in `pyproject.toml`, `hwp_live`, MCP
      initialization, changelog, and release notes.
- [ ] Create `v0.3.0-rc.1` as a GitHub pre-release only after this gate passes.
- [ ] Do not publish to PyPI during the initial source/Release phase.
