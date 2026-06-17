from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thread_continuity.api import ThreadContinuity
from thread_continuity.bootstrap import doctor, install_notes, mcp_config
from thread_continuity.server import handle_request
from thread_continuity.store import ThreadStore


class ThreadContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.archived = self.root / "archived"
        self.memory = self.root / "memories"
        self.sessions.mkdir()
        self.archived.mkdir()
        self.memory.mkdir()
        self.db_path = self.root / "index.sqlite3"
        self.config_path = self.root / "sources.json"
        self.export_path = self.root / "pack.md"
        self._write_session()
        (self.memory / "MEMORY.md").write_text(
            "# Task Group: thread continuity\n\n- thread search plugin proof and blocker notes\n",
            encoding="utf-8",
        )
        self.env = {
            "CODEX_SESSION_ROOT": str(self.sessions),
            "CODEX_ARCHIVED_SESSION_ROOT": str(self.archived),
            "CODEX_MEMORY_ROOT": str(self.memory),
            "THREAD_CONTINUITY_DB": str(self.db_path),
            "THREAD_CONTINUITY_CONFIG": str(self.config_path),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_index_search_resume_and_pack(self) -> None:
        with patch.dict(os.environ, self.env, clear=False):
            api = ThreadContinuity(ThreadStore())
            try:
                indexed = api.thread_index(force=True)
                self.assertEqual(indexed["indexed_threads"], 2)
                self.assertGreater(indexed["indexed_messages"], 0)

                search = api.thread_search("where implemented omnisocials queue review", limit=3)
                self.assertEqual(search["intent"], "find_implementation")
                self.assertTrue(search["candidates"])
                top = search["candidates"][0]
                self.assertEqual(top["source"], "codex")
                self.assertIn("confidence", top)
                self.assertLessEqual(len(top["evidence"][0]["snippet"]), 260)

                resume = api.thread_resume("resume building OmniSocials queue review", limit=2)
                self.assertEqual(resume["intent"], "resume_work")
                self.assertIn("next_best_action", resume["candidates"][0])

                pack = api.thread_pack(top["thread_id"], focus="OmniSocials")
                self.assertTrue(pack["found"])
                self.assertLessEqual(len(pack["evidence"]), 8)
                self.assertIn("objective", pack)
            finally:
                api.close()

    def test_thread_get_hides_tool_outputs_by_default(self) -> None:
        with patch.dict(os.environ, self.env, clear=False):
            api = ThreadContinuity(ThreadStore())
            try:
                api.thread_index(force=True)
                result = api.thread_search("proof command", limit=1)
                thread_id = result["candidates"][0]["thread_id"]
                thread = api.thread_get(thread_id, include_messages=True, include_outputs=False)
                self.assertTrue(thread["found"])
                self.assertTrue(thread["messages"])
                self.assertTrue(all(message["role"] != "tool" for message in thread["messages"]))
            finally:
                api.close()

    def test_mcp_tools_list_and_call(self) -> None:
        with patch.dict(os.environ, self.env, clear=False):
            api = ThreadContinuity(ThreadStore())
            try:
                listed = handle_request(api, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                names = {tool["name"] for tool in listed["result"]["tools"]}
                self.assertIn("thread_search", names)
                self.assertIn("thread_sources_status", names)
                self.assertIn("thread_index_status", names)
                self.assertIn("thread_sources_add", names)
                self.assertIn("thread_export", names)
                self.assertIn("thread_eval", names)
                called = handle_request(
                    api,
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "thread_triage", "arguments": {}},
                    },
                )
                text = called["result"]["content"][0]["text"]
                payload = json.loads(text)
                self.assertIn("sources", payload)
            finally:
                api.close()

    def test_source_add_export_open_ref_and_eval(self) -> None:
        with patch.dict(os.environ, self.env, clear=False):
            api = ThreadContinuity(ThreadStore())
            try:
                added = api.thread_sources_add(
                    path_or_profile=str(self.sessions),
                    source_type="codex",
                    name="fixture sessions",
                )
                self.assertTrue(added["ok"])
                sources = api.thread_sources_status()["sources"]
                self.assertTrue(any(source.get("profile_id") == added["profile"]["id"] for source in sources))

                api.thread_index(force=True)
                result = api.thread_search("OmniSocials queue review", limit=1)
                thread_id = result["candidates"][0]["thread_id"]

                exported = api.thread_export(
                    thread_id,
                    focus="OmniSocials",
                    format="markdown",
                    output_path=str(self.export_path),
                )
                self.assertTrue(exported["ok"])
                self.assertTrue(self.export_path.is_file())
                self.assertIn("Thread Pack", self.export_path.read_text(encoding="utf-8"))

                open_ref = api.thread_open_ref(thread_id)
                self.assertTrue(open_ref["ok"])
                self.assertFalse(open_ref["open_supported"])

                evaluation = api.thread_eval(limit=2)
                self.assertEqual(evaluation["case_count"], 10)
                self.assertIn("pass_rate", evaluation)
                self.assertTrue(evaluation["results"])
            finally:
                api.close()

    def test_bootstrap_doctor_mcp_config_and_install_notes(self) -> None:
        with patch.dict(os.environ, self.env, clear=False):
            report = doctor()
            self.assertIn("checks", report)
            self.assertIn("next_steps", report)
            self.assertEqual(report["paths"]["db"], str(self.db_path))

            source_config = mcp_config(mode="source", cwd=str(self.root))
            server = source_config["mcpServers"]["thread-continuity"]
            self.assertIn("-m", server["args"])
            self.assertEqual(server["cwd"], str(self.root))

            installed_config = mcp_config(mode="installed")
            installed_server = installed_config["mcpServers"]["thread-continuity"]
            self.assertIn("command", installed_server)

            notes = install_notes()
            self.assertIn("local CLI plus MCP server", notes["recommended_shape"])

    def test_installer_script_is_valid_bash(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "install-local.sh"
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _write_session(self) -> None:
        path = self.sessions / "rollout-2026-06-17T00-00-00-019ed000-0000-7000-8000-000000000001.jsonl"
        rows = [
            {
                "timestamp": "2026-06-17T12:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "019ed000-0000-7000-8000-000000000001",
                    "timestamp": "2026-06-17T12:00:00Z",
                    "cwd": "/tmp/workspaces/social-media-manager",
                },
            },
            {
                "timestamp": "2026-06-17T12:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Resume building the OmniSocials queue review and find the proof command.",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-06-17T12:02:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": "{\"cmd\":\"npm test -- queue-review\"}",
                },
            },
            {
                "timestamp": "2026-06-17T12:03:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Implemented queue review in /tmp/workspaces/social-media-manager/src/queue.ts. Remaining blocker: auth token must be refreshed before live posting. Next: run npm test -- queue-review.",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-06-17T12:04:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "output": "curl 'http://localhost:8645/bluebubbles-webhook?password=sekrit123&limit=1' Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
                },
            },
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    def test_responses_redact_sensitive_values(self) -> None:
        with patch.dict(os.environ, self.env, clear=False):
            api = ThreadContinuity(ThreadStore())
            try:
                api.thread_index(force=True)
                search = json.dumps(api.thread_search("bluebubbles webhook password", limit=1))
                self.assertNotIn("sekrit123", search)
                self.assertNotIn("abcdefghijklmnopqrstuvwxyz", search)
                self.assertIn("<redacted>", search)

                thread_id = json.loads(search)["candidates"][0]["thread_id"]
                thread = json.dumps(api.thread_get(thread_id, include_messages=True, include_outputs=True))
                self.assertNotIn("sekrit123", thread)
                self.assertNotIn("abcdefghijklmnopqrstuvwxyz", thread)
            finally:
                api.close()


if __name__ == "__main__":
    unittest.main()
