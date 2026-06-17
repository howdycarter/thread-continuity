# Thread Continuity Runnable Goal

## Objective

Make Thread Continuity easy for other users to install and run as a local CLI plus MCP service, with a safe installer, doctor/config commands, docs, and passing verification.

## Source Of Truth

- PRD: local product requirements document for cross-agent thread search.
- Plugin repo: this repository.

## Done When

- A user has a one-command local installer.
- Installed users get `thread-continuity` and `thread-continuity-mcp` commands.
- `doctor` reports readiness and next steps.
- `mcp-config` prints copyable MCP configuration for installed and source modes.
- Docs explain that the core is CLI/MCP, with a Mac app as optional future UI.
- Existing plugin tests, validation, and smoke checks pass.

## Acceptance Criteria

- Plugin scaffold exists: `.codex-plugin/plugin.json`, `.mcp.json`, and `skills/thread-continuity/SKILL.md`.
- MCP/API/CLI expose `thread_triage`, `thread_sources_status`, `thread_index_status`, `thread_search`, `thread_resume`, `thread_get`, `thread_pack`, `thread_sources_add`, `thread_open_ref`, `thread_export`, and `thread_eval`.
- Codex JSONL and memory sources index read-only into SQLite FTS.
- CASS, Claude Code, and Cursor are detected and reported with honest availability/status; Claude Code JSONL and Cursor composer/bubble storage are ingested read-only when available.
- Thread pack export supports Markdown and HTML.
- Eval harness returns stable JSON with pass/fail cases, latency, warnings, and summary metrics.
- Safety tests cover redaction and no raw tool-output exposure by default.
- Distribution docs and install script make the CLI/MCP run path clear.
- Console scripts are declared in `pyproject.toml`.

## Constraints

- Local-only by default.
- No browser cookies, credentials, or local storage reads.
- No hosted sync, transcript upload, model download, marketplace install, public push, or publication without explicit approval.
- Old threads are historical evidence only; they are never current runtime truth.

## Non-Goals

- Hosted/cloud transcript sync.
- Semantic embeddings.
- App/dashboard UI.
- Team/shared sync.
- Public marketplace release.

## Verifier

```bash
python3 -m unittest discover -s tests -v
python3 path/to/validate_plugin.py .
THREAD_CONTINUITY_DB=/tmp/thread-continuity-smoke.sqlite3 python3 -m thread_continuity.cli index --max-threads 20
THREAD_CONTINUITY_DB=/tmp/thread-continuity-smoke.sqlite3 python3 -m thread_continuity.cli eval --limit 5
```

## Blocker Standard

Only mark blocked after three consecutive attempts fail on the same missing platform/tooling capability and no safe fallback remains.
