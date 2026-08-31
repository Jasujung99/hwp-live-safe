## Summary

Describe the user-visible change and why it belongs in HWP Live Safe.

## Safety and privacy impact

- Does this change affect preview, approval, document ownership, Undo, profile
  handling, foreground typing, or returned MCP content?
- Confirm that no real document, profile value, token, personal path, or
  sensitive screenshot is included.

## Verification

- [ ] Unit tests pass.
- [ ] Fake MCP smoke test passes and still exposes exactly the intended tools.
- [ ] Public-repository privacy check passes.
- [ ] Wheel/source distribution build and privacy/entry-point inspection pass.
- [ ] Documentation and known limitations are updated when behavior changed.
- [ ] A real Hancom test was either unnecessary or performed only with the
      disposable-document release checklist, with redacted results recorded.
