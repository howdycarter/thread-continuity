# Distribution Plan

Thread Continuity should ship as a local-first CLI plus MCP server. A Mac app can come later as a setup/search UI, but it should not be the core product.

## Product Shape

```text
Local source files -> SQLite/FTS index -> CLI + MCP server -> Codex/Claude/Cursor/other agents
```

## Install Path For Users

From the repo:

```bash
./scripts/install-local.sh
thread-continuity doctor
thread-continuity mcp-config --mode installed
thread-continuity index
thread-continuity resume "building X"
```

This creates:

- `~/.thread-continuity/venv`
- `~/.local/bin/thread-continuity`
- `~/.local/bin/thread-continuity-mcp`

No source transcripts are uploaded. The index stays local at `~/.codex/thread-continuity/index.sqlite3` unless overridden.

## Agent Setup

After install, run:

```bash
thread-continuity mcp-config --mode installed
```

Add the returned `mcpServers.thread-continuity` block to the MCP client configuration. The installed MCP command is:

```bash
thread-continuity-mcp
```

For development from this repo without installing:

```bash
python3 -m thread_continuity.cli mcp-config --mode source
```

## Why Not Start With A Mac App

A Mac app would help with onboarding, source status, and browsing results, but it adds signing, permissions, updates, and UI maintenance before the retrieval core has earned it. The MVP value is agents being able to ask:

- "Resume building X."
- "Where did we implement X?"
- "What changed and what is stale?"

That value lives in a local indexer and MCP interface first.

## Future Packaging Options

- Homebrew tap for Mac/Linux CLI installs.
- PyPI package once the API stabilizes.
- npm wrapper only if JavaScript-based MCP clients need it.
- Optional signed Mac app for setup, status, and visual search.
- Optional launchd service for background indexing.

## Release Gates

- Full golden eval corpus, not only smoke eval.
- Real CASS wrapping when installed.
- Claude Code and Cursor parsers upgraded from detection to ingestion.
- Installer rollback/uninstall path.
- Security review for transcript redaction and source discovery.
