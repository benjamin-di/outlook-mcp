# Progress — outlook-mcp-dev

Newest first. Every worker session prepends: date, task, key outcomes, files/test evidence, notes for the next worker.

## 2026-10-12 — initializer

- Mission created: close the gap between what outlook-mcp promises and what it does, offline only. Queue seeded with 7 tasks: two contact fixes Neil filed (#119, #120), the 412 hint (#96), a docs truth audit, Actions SHA pinning, the live test for #98, and a kiota cap check.
- Left out on purpose: #74 (Michael asked Neil to take it on 2026-09-22), #121 (a new tool that needs live verification), #97/#70/#72 (live-only; a `live-gap-*` card each once #98's pattern is proven).
- Guard verified on Neo before the first session: with `OUTLOOK_MCP_CONFIG_DIR` pointed at the sealed directory the server's own startup check finds no client id and no token, and even a credential handed the real client id is refused (`AuthenticationRequiredError`) because no account record exists. Offline suite under the guard: 1335 passed, 83 deselected; ruff check and format clean.
- Note for first worker: read MISSION.md's Boundaries in full before anything else. The suite command is the first line of MISSION.md.
