from __future__ import annotations

from typing import Any

from .adapters import iter_records, source_status
from .eval import run_eval
from .export import write_pack
from .sources import add_profile
from .store import ThreadStore
from .utils import cass_status, compact_text, infer_intent, now_iso, stable_id


class ThreadContinuity:
    def __init__(self, store: ThreadStore | None = None) -> None:
        self.store = store or ThreadStore()

    def close(self) -> None:
        self.store.close()

    def thread_sources_list(self) -> dict[str, Any]:
        sources = source_status()
        sources.append(
            {
                "source": "cass",
                "kind": "external-cli",
                **cass_status(),
            }
        )
        return {"sources": sources}

    def thread_sources_status(self) -> dict[str, Any]:
        return self.thread_sources_list()

    def thread_index_status(self) -> dict[str, Any]:
        return self.store.index_status()

    def thread_sources_add(
        self,
        path_or_profile: str,
        source_type: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        return add_profile(path_or_profile=path_or_profile, source_type=source_type, name=name)

    def thread_triage(self) -> dict[str, Any]:
        return {
            "checked_at": now_iso(),
            "sources": self.thread_sources_list()["sources"],
            "index": self.store.index_status(),
            "next_command": "thread_index(force=false) if index is empty or stale; otherwise thread_search/thread_resume",
            "privacy": {
                "local_only": True,
                "reads_credentials": False,
                "uploads_transcripts": False,
            },
        }

    def thread_index(
        self,
        *,
        force: bool = False,
        source: str = "all",
        max_threads: int | None = None,
    ) -> dict[str, Any]:
        started_at = now_iso()
        if force:
            self.store.clear_source(source)
        indexed_threads = 0
        indexed_messages = 0
        warnings: list[str] = []
        for status in source_status():
            self.store.record_health(status["source"], status)
        for record in iter_records(source=source, max_threads=max_threads):
            indexed_threads += 1
            indexed_messages += self.store.upsert_thread(record)
            if record.source_status != "indexed":
                warnings.append(f"{record.thread_id}: {record.source_status}")
        self.store.record_index_run(
            source=source,
            indexed_threads=indexed_threads,
            indexed_messages=indexed_messages,
            started_at=started_at,
            warnings=warnings,
        )
        return {
            "source": source,
            "indexed_threads": indexed_threads,
            "indexed_messages": indexed_messages,
            "started_at": started_at,
            "finished_at": now_iso(),
            "warnings": warnings[:50],
            "index": self.store.index_status(),
        }

    def thread_search(
        self,
        query: str,
        *,
        workspace: str | None = None,
        source: str | None = None,
        limit: int = 5,
        mode: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_index()
        intent = mode or infer_intent(query)
        candidates = self.store.search(query, workspace=workspace, source=source, limit=limit)
        result_id_prefix = stable_id(f"{query}:{workspace}:{source}:{intent}")
        for index, candidate in enumerate(candidates, start=1):
            candidate["result_id"] = f"{result_id_prefix}-{index}"
            candidate["intent"] = intent
        return {
            "query": query,
            "intent": intent,
            "candidates": candidates,
            "warnings": self._global_warnings(candidates),
        }

    def thread_resume(
        self,
        query: str,
        *,
        workspace: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        search = self.thread_search(query, workspace=workspace, limit=limit, mode="resume_work")
        for candidate in search["candidates"]:
            derived = candidate.get("derived", {})
            candidate["last_known_state"] = derived.get("summary") or candidate.get("title")
            candidate["next_best_action"] = self._next_best_action(candidate)
        return search

    def thread_pack(self, thread_id: str, *, focus: str | None = None) -> dict[str, Any]:
        thread = self.store.get_thread(thread_id, include_messages=True)
        if thread is None:
            return {
                "thread_id": thread_id,
                "found": False,
                "warnings": ["thread_id not found in local index"],
            }
        messages = thread.pop("messages", [])
        focus_terms = [term.lower() for term in (focus or "").split() if term.strip()]
        evidence = []
        for message in messages:
            text = message["text"]
            lowered = text.lower()
            if not focus_terms or any(term in lowered for term in focus_terms):
                evidence.append(
                    {
                        "role": message["role"],
                        "source_ref": message.get("line_ref") or thread["source_path"],
                        "snippet": compact_text(text, limit=500),
                    }
                )
            if len(evidence) >= 8:
                break
        derived = thread.get("derived", {})
        return {
            "thread_id": thread_id,
            "found": True,
            "source": thread["source"],
            "title": thread["title"],
            "workspace": thread["workspace"],
            "status": thread["status"],
            "updated_at": thread["updated_at"],
            "objective": derived.get("objective"),
            "summary": derived.get("summary"),
            "blockers": derived.get("blockers", [])[:5],
            "next_steps": derived.get("next_steps", [])[:5],
            "files_touched": derived.get("files_touched", [])[:10],
            "proof_links": derived.get("proof_links", [])[:10],
            "evidence": evidence,
            "warnings": self._global_warnings([thread]),
        }

    def thread_export(
        self,
        thread_id: str,
        *,
        focus: str | None = None,
        format: str = "markdown",
        output_path: str | None = None,
    ) -> dict[str, Any]:
        pack = self.thread_pack(thread_id, focus=focus)
        if not pack.get("found"):
            return {"ok": False, "thread_id": thread_id, "warnings": pack.get("warnings", [])}
        export = write_pack(pack, export_format=format, output_path=output_path)
        export["thread_id"] = thread_id
        return export

    def thread_get(
        self,
        thread_id: str,
        *,
        include_messages: bool = False,
        include_outputs: bool = False,
    ) -> dict[str, Any]:
        thread = self.store.get_thread(thread_id, include_messages=include_messages)
        if thread is None:
            return {"found": False, "thread_id": thread_id}
        if include_messages and not include_outputs:
            thread["messages"] = [
                message for message in thread.get("messages", []) if message.get("role") != "tool"
            ]
        thread["found"] = True
        return thread

    def thread_explain_result(self, result_id: str) -> dict[str, Any]:
        return {
            "result_id": result_id,
            "ranking_inputs": [
                "lexical message/title match",
                "workspace match when provided",
                "recency boost",
                "known outcome/status",
                "artifact/file refs",
            ],
            "note": "Result ids are stable within a single query response; re-run search for full candidate context.",
        }

    def thread_open_ref(self, thread_id: str) -> dict[str, Any]:
        thread = self.store.get_thread(thread_id, include_messages=False)
        if thread is None:
            return {"ok": False, "thread_id": thread_id, "warnings": ["thread_id not found in local index"]}
        return {
            "ok": True,
            "thread_id": thread_id,
            "source": thread["source"],
            "source_ref": thread["source_path"],
            "open_supported": False,
            "note": "Host-level thread opening is not available from this local MCP server; use source_ref or thread_pack.",
        }

    def thread_eval(self, *, limit: int = 5) -> dict[str, Any]:
        self._ensure_index()
        return run_eval(self, limit=limit)

    def _ensure_index(self) -> None:
        status = self.store.index_status()
        if status["thread_count"] == 0:
            self.thread_index(force=False, source="all")

    def _next_best_action(self, candidate: dict[str, Any]) -> str:
        derived = candidate.get("derived", {})
        if derived.get("next_steps"):
            return derived["next_steps"][0]
        if derived.get("blockers"):
            return "Re-check blocker before continuing: " + derived["blockers"][0]
        if candidate.get("status") == "done":
            return "Verify current repo/runtime truth before treating old completion as current."
        return "Open thread pack, verify current workspace state, then continue from the cited evidence."

    def _global_warnings(self, candidates: list[dict[str, Any]]) -> list[str]:
        warnings: list[str] = []
        if not candidates:
            warnings.append("no confident local match")
        if not cass_status()["available"]:
            warnings.append("cass unavailable; using Codex-native local index only")
        for candidate in candidates:
            for warning in candidate.get("warnings", []):
                if warning not in warnings:
                    warnings.append(warning)
        return warnings[:8]
