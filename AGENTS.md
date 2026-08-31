# HWP Live Safe agent contract

Use the native MCP tools only for the visible HWP Live Safe session they created.

1. Call `hwp_start_new_document` before a write. It creates a fresh unsaved
   document and never attaches to an existing user file.
2. Call `hwp_read_context`, then use its `revision` for a preview.
3. For every change, call `hwp_preview_edits`. Apply a short, explicit,
   structured request in the same turn; show long-form, ambiguous, or
   replacement text for approval before applying it.
4. The first version may insert text and non-empty tables only. It has no open,
   save, export, close, delete, or arbitrary-action tool.
5. If the user manually changes the document, read the context again. HWP Live Safe
   discards stale previews and will refuse an unsafe undo.
6. Use `hwp_undo_last` only for the immediately preceding, unchanged HWP Live Safe
   change.
7. For a local profile, call `hwp_profile_list` and then
   `hwp_preview_profile_insert`. Never repeat or infer a profile value in chat;
   the preview intentionally exposes only the profile/key label. Apply only
   after the user confirms the visible target caret.
8. `hwp_foreground_*` is experimental literal UI typing, not native document
   attachment. Use it only when the user has explicitly identified a listed
   Hancom window and explicitly confirmed one collapsed caret in the desired
   tab. It is limited to one reviewed short insertion; never use it for tables,
   selected-range replacement, batch/long-form text, or automatic Undo.
