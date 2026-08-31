# Security policy

HWP Live Safe is designed for local use, but it can insert sensitive values
into a visible document. Treat its MCP client, profile directory, and the
visible Hancom window as part of the trusted local boundary.

## Reporting a vulnerability

Do not put real documents, profile files, window titles, access tokens, or
personal data in a public issue. Use
[GitHub private vulnerability reporting](https://github.com/Jasujung99/hwp-live-safe/security/advisories/new)
for a confidential report. Include the release version, Windows and Hancom
version, the smallest non-sensitive reproduction, expected behavior, and
observed behavior. If that private form is unavailable, do not fall back to a
public issue; wait for the repository owner to restore the private channel.

## Safe operating assumptions

- The server exposes no HTTP listener and makes no cloud API request itself.
- MCP clients can still receive document text returned by `hwp_read_context`.
  Use a client and model provider you trust before reading a document that
  contains sensitive information.
- Profile values remain local during profile preview, but become part of the
  document after applying the change. Reading that document later can expose
  the inserted value to the MCP client.
- Do not copy a real profile JSON file into this repository. The supplied
  `profiles/profile.example.json` must remain value-free.
- Review every foreground-typing preview in the visible Hancom window. That
  experimental path has no document read-back or automatic undo.
