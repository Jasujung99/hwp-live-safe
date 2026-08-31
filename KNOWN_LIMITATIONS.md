# Known limitations

## Supported environment

This pre-release candidate is developed for Windows with the 32-bit automation
registration supplied by Hancom Office 2022. It starts a visible, new,
unsaved document that it owns. Other Hancom versions and existing document
attachment are not supported claims.

The automated public baseline and the fail-closed existing-window preflight
have passed. The complete real-Hancom manual gate is not yet recorded, so this
source candidate has no tag or GitHub Release and is not a general support
claim for Hancom Office 2022 installations.

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
