# Thread Continuity Worklog

## 2026-06-17

- Activated runnable goal from the PRD.
- Baseline: existing Codex-native MVP was present but uncommitted; durable goal docs and several PRD tool surfaces were missing.
- Planned additions: source profiles/status, Claude/Cursor/CASS honest discovery, pack export, eval harness, expanded tests, and final verifier proof.
- Added durable `GOAL.md`, `WORKLOG.md`, and pending `RESULT.md`.
- Added source profile registration, Claude/Cursor detection status, `thread_export`, `thread_open_ref`, and `thread_eval`.
- Expanded CLI and MCP schemas for the new tool surface.
- Added tests for profile registration, export, open-ref, eval, and redaction behavior.
- Verified with 5 unit tests, official plugin validation, bounded real-history indexing, 10/10 smoke eval, markdown export, and open-ref fallback.
- Activated follow-up distribution goal after a product-shape question about whether this should be a Mac app.
- Added the decision: core product is local CLI plus MCP server; Mac app is optional future UI.
- Added installer/doctor/MCP-config workstream.
- Added `thread-continuity` and `thread-continuity-mcp` console scripts.
- Added `thread_continuity/bootstrap.py` for `doctor`, `mcp-config`, and install notes.
- Added `scripts/install-local.sh` and `DISTRIBUTION.md`.
- Fixed Python package discovery so editable installs include only `thread_continuity`.
- Verified a temp install under `/tmp/thread-continuity-install-venv` and `/tmp/thread-continuity-bin`.
- Tested real local Claude Code sources and found 32 JSONL files were detectable but not ingested.
- Added a read-only Claude Code JSONL parser and enabled `thread_index(source="claude_code")`.
- Verified Claude-only indexing, search, pack, and default tool-output hiding against real local Claude Code history.
- Verified combined Codex + memory + Claude indexing in one SQLite database.
- Tested real local Cursor after Chris created a Cursor thread and found storage in `state.vscdb` `cursorDiskKV`.
- Added a read-only Cursor composer/bubble parser that avoids credential keys and enables `thread_index(source="cursor")`.
- Verified Cursor-only indexing, search, pack, and default tool-output hiding against the real Cursor thread.
- Verified combined Codex + memory + Claude + Cursor indexing in one SQLite database.
