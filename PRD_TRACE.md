# PRD Implementation Trace

## Phase 0 - Spike Existing Engines

| Requirement | Status | Evidence |
|---|---|---|
| Check whether CASS is installed | Done | `thread_triage` and `thread_sources_status` report CASS availability. |
| Fallback when CASS is unavailable | Done | Codex-native SQLite indexer runs without CASS. |
| Compare against live Codex thread APIs | Deferred | Host thread APIs are not exposed inside the plugin server; the skill instructs agents to prefer live APIs when available. |

## Phase 1 - Codex-Native MVP

| Requirement | Status | Evidence |
|---|---|---|
| Plugin scaffold | Done | `.codex-plugin/plugin.json`, `.mcp.json`, `skills/thread-continuity/SKILL.md`. |
| MCP tools | Done | `thread_triage`, `thread_search`, `thread_resume`, `thread_pack`, plus PRD support tools. |
| Read-only Codex local adapter | Done | `thread_continuity/adapters.py` parses `~/.codex/sessions` and archived sessions. |
| SQLite FTS index | Done | `thread_continuity/store.py` uses SQLite FTS5 when available. |
| Resume packet builder | Done | `thread_resume` and `thread_pack` return status, source refs, confidence, warnings, evidence, and next action. |

## Phase 2 - Cross-Harness

| Requirement | Status | Evidence |
|---|---|---|
| Claude Code adapter | Done | `thread_sources_status` reports `~/.claude/projects` availability and `thread_index(source="claude_code")` ingests Claude Code JSONL read-only. |
| Cursor adapter | Done | `thread_sources_status` reports Cursor storage availability and `thread_index(source="cursor")` ingests Cursor composer/bubble storage read-only. |
| CASS adapter | Detection done, wrapping deferred | `cass` availability is reported; fallback is used when absent. |
| Source filters and source health | Done | Search supports `source`; `source_health` and source status are recorded. |
| Thread pack export | Done | `thread_export` writes Markdown or HTML compact packs. |

## Phase 3 - Quality And Trust

| Requirement | Status | Evidence |
|---|---|---|
| Golden eval suite | Smoke eval done, golden corpus deferred | `thread_eval` implements the PRD query set as a local smoke health check. |
| Staleness labels | Done | Search/resume warnings include stale candidate age. |
| Result explanation | Done | `thread_explain_result` documents ranking inputs. |
| Redaction and safe snippets | Done | Tests cover password/Bearer redaction and tool-output hiding by default. |
| Optional embeddings | Deferred | Non-goal for the runnable local MVP; no model downloads occur. |

## Known Gaps

- Cursor support targets local composer/bubble storage and may need updates if Cursor changes storage shape.
- The eval harness is not a substitute for the PRD's 60-100 session golden corpus.
- `thread_open_ref` returns a local source reference because host-level thread opening is not available from the MCP server.

## Distribution Trace

| Requirement | Status | Evidence |
|---|---|---|
| Easy local install | Done | `scripts/install-local.sh` creates a venv and symlinks commands. |
| Human CLI | Done | `thread-continuity` console script. |
| Agent MCP server | Done | `thread-continuity-mcp` console script. |
| Setup diagnostics | Done | `thread-continuity doctor`. |
| Copyable MCP config | Done | `thread-continuity mcp-config --mode installed` and `--mode source`. |
| Mac app clarity | Done | `DISTRIBUTION.md` documents Mac app as future UI, not core product. |
