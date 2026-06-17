---
name: thread-continuity
description: Search local agent history before claiming prior work, resuming a task, or locating the thread where an implementation, blocker, proof, artifact, or decision happened.
---

# Thread Continuity

Use this skill when the user asks to resume prior work, find where something was implemented, locate a blocker/proof/artifact/decision, or says "we already built this" and the current thread does not contain enough evidence.

## Required Behavior

1. Prefer live host thread APIs when they are available in the current tool list.
2. Otherwise call the `thread-continuity` MCP tools:
   - `thread_triage` to inspect source/index readiness.
   - `thread_resume` for continuation requests.
   - `thread_search` for known-item or evidence lookup.
   - `thread_pack` before continuing from a specific thread.
   - `thread_export` when the user needs a shareable local continuation packet.
   - `thread_eval` after implementation or source changes to check retrieval health.
3. Report source, workspace, confidence, and staleness. Old threads are evidence, not current runtime truth.
4. Keep private transcript text minimal. Use short evidence snippets and local refs instead of dumping full messages.
5. If confidence is low or multiple candidates are plausible, present the candidates and ask for disambiguation before mutating files.

## Query Routing

- "Resume building X" -> `thread_resume`.
- "Where did we implement X?" -> `thread_search` with implementation intent.
- "Find the blocker/proof/artifact/decision" -> `thread_search`.
- "Give me the context before continuing" -> `thread_pack` for the best candidate after search.

## Safety

Do not read browser cookies, credential stores, or local storage for thread discovery. Do not upload local session content to remote services. Do not treat a stale indexed result as proof that the current repo, PR, deploy, or task ledger is done.
