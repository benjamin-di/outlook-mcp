# Progress — outlook-mcp-dev

Newest first. Every worker session prepends: date, task, key outcomes, files/test evidence, notes for the next worker.

## 2026-10-13 — contact-job-title (#119)

- Re-checked #119: open, unassigned, no comments, no linked PR (search hit #63 is an older, unrelated merged PR).
- `outlook_create_contact` and `outlook_update_contact` take `job_title` → Graph `jobTitle`; `outlook_get_contact` returns `job_title`. `title` kept as-is, described as the name prefix in the create docstring, README and SKILL.md. CHANGELOG under Unreleased → Fixed.
- TDD: wire tests (create sentinel lands under `"jobTitle"`, `"title"` absent when only a job is given; update carries `jobTitle`) and the detail-format tests failed first (TypeError / KeyError), then green.
- `tests/test_live_contacts_write.py` edited (prefix in `title`, job in `job_title`, display name not prefixed by the job; update persists `job_title`). NOT run — parked as `[?]` contact-job-title-live.
- Suite: 1336 passed, 83 deselected; ruff check + format clean. Tool surface 13,024 → 13,100 proxy tokens (ceiling 13,300, no raise; note the budget header's last recorded 13,245 is stale-high).
- Queued follow-up contact-title-on-update (update cannot fix a wrong prefix in place).
- Env note for next worker: `uv` is at `~/.local/bin/uv` (not on PATH) and needs `UV_CACHE_DIR=$TMPDIR/uv-cache` under the sandbox; `gh` needs the sandbox off (TLS).

## 2026-10-12 — initializer

- Mission created: close the gap between what outlook-mcp promises and what it does, offline only. Queue seeded with 7 tasks: two contact fixes Neil filed (#119, #120), the 412 hint (#96), a docs truth audit, Actions SHA pinning, the live test for #98, and a kiota cap check.
- Left out on purpose: #74 (Michael asked Neil to take it on 2026-09-22), #121 (a new tool that needs live verification), #97/#70/#72 (live-only; a `live-gap-*` card each once #98's pattern is proven).
- Guard verified on Neo before the first session: with `OUTLOOK_MCP_CONFIG_DIR` pointed at the sealed directory the server's own startup check finds no client id and no token, and even a credential handed the real client id is refused (`AuthenticationRequiredError`) because no account record exists. Offline suite under the guard: 1335 passed, 83 deselected; ruff check and format clean.
- Note for first worker: read MISSION.md's Boundaries in full before anything else. The suite command is the first line of MISSION.md.
