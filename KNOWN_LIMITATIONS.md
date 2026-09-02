# Known limitations

## Supported environment

The native safe mode was manually witnessed on 2026-09-02 with Windows 10 Home
22H2 (build `22621.4317`), Hancom Office 2022 executable `12.0.0.850`, Python
`3.12.13`, MCP Python SDK `2.1.1`, Codex CLI `0.147.0`, and the 32-bit
`HWPFrame.HwpObject` automation registration. The native-safe evidence used
source commit `72cda61`; the experimental foreground path was re-witnessed
after its fixes at `0436e9a`. The test used a new unsaved document and dummy
profile data.

The automated public baseline and complete scoped manual gate passed for that
configuration. The manual evidence covers native document creation; reviewed
text and table preview/apply/read-back; dummy-profile insertion privacy;
stale-preview rejection; safe Undo; and one short experimental foreground
insertion at a user-confirmed collapsed caret.

This is not a broad compatibility claim. Other Windows editions/builds, Hancom
versions or architectures, Python/MCP/client versions, and attachment to an
existing document remain unverified or unsupported.

## Native safe mode

- It will not open, save, save as, close, export, delete, or overwrite a user
  file.
- It supports one reviewed text insertion or one non-empty table insertion per
  preview. Native text formatting is limited to size, bold, and paragraph
  alignment in this release candidate.
- Header bold/fill supplied with a table is reported as a follow-up warning;
  it is not silently applied.
- The text fingerprint detects text changes, not every possible visual or
  metadata-only Hancom change. If you edit the document manually, read its
  context again and create a new preview.
- Undo is available only for the immediately preceding unchanged HWP Live Safe
  edit. It intentionally refuses if it cannot verify the expected state.
- Native mode validates that its COM instance owns exactly one blank, unsaved
  document represented by a unique new window. It does not attach to any
  pre-existing window. Set `HWP_LIVE_SAFE_STRICT_ISOLATION=1` when coexistence
  with another Hancom process is not desired.
- Worker operations have finite deadlines. After a timeout, the backend refuses
  to launch a replacement worker until shutdown because the timed-out mutation's
  outcome may be unknown. Modal Hancom dialogs can therefore require manual
  inspection and a clean restart.
- The coexistence, formatting-restoration, table-exit, and modal-timeout changes
  in `Unreleased` require the next real-Hancom manual release gate; automated
  tests cover their fail-closed contracts but are not UI compatibility evidence.

## Experimental foreground typing

- This is literal keyboard input into one explicitly selected visible Hancom
  window, not a native attachment to its file or selection.
- It cannot read the existing document, inspect a caret or selection, replace
  selected text, create a table, batch-edit, or automatically undo.
- It is suitable only for one short, approved insertion at a user-confirmed
  collapsed caret. The user must verify the result immediately in Hancom.

## Product scope

HWP Live Safe is an independent open-source project. It is not affiliated with
or endorsed by Hancom. "Hancom" and "HWP" may be trademarks of their
respective owners.
