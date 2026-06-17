from __future__ import annotations

import platform
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .adapters import source_status
from .store import ThreadStore
from .utils import default_config_path, default_db_path, env_path, now_iso


def doctor() -> dict[str, Any]:
    store = ThreadStore()
    try:
        index = store.index_status()
    finally:
        store.close()
    cli_status = _command_status("thread-continuity", fallback_module="thread_continuity.cli")
    mcp_status = _command_status("thread-continuity-mcp", fallback_module="thread_continuity.server")
    checks = [
        {
            "name": "python_version",
            "ok": sys.version_info >= (3, 11),
            "detail": platform.python_version(),
        },
        {
            "name": "sqlite",
            "ok": True,
            "detail": sqlite3.sqlite_version,
        },
        {
            "name": "sqlite_fts",
            "ok": bool(index.get("fts")),
            "detail": "FTS5 available" if index.get("fts") else "FTS5 unavailable; LIKE fallback will be used",
        },
        {
            "name": "cli_command",
            "ok": cli_status["ok"],
            "detail": cli_status["detail"],
        },
        {
            "name": "mcp_command",
            "ok": mcp_status["ok"],
            "detail": mcp_status["detail"],
        },
    ]
    return {
        "checked_at": now_iso(),
        "ok": all(check["ok"] for check in checks[:2]),
        "checks": checks,
        "paths": {
            "db": str(default_db_path()),
            "config": str(default_config_path()),
            "exports": str(env_path("THREAD_CONTINUITY_EXPORT_ROOT", "~/.codex/thread-continuity/exports")),
        },
        "sources": source_status(),
        "index": index,
        "next_steps": _doctor_next_steps(checks, index),
    }


def mcp_config(*, mode: str = "installed", cwd: str | None = None) -> dict[str, Any]:
    if mode == "source":
        command = sys.executable
        args = ["-m", "thread_continuity.server"]
        resolved_cwd = cwd or str(Path(__file__).resolve().parents[1])
    else:
        command = shutil.which("thread-continuity-mcp") or "thread-continuity-mcp"
        args = []
        resolved_cwd = cwd
    server: dict[str, Any] = {
        "command": command,
        "args": args,
    }
    if resolved_cwd:
        server["cwd"] = resolved_cwd
    return {
        "mcpServers": {
            "thread-continuity": server,
        }
    }


def install_notes() -> dict[str, Any]:
    return {
        "recommended_shape": "local CLI plus MCP server; Mac app is optional future UI",
        "install_commands": [
            "python3 -m venv .venv",
            ". .venv/bin/activate",
            "python3 -m pip install -e .",
            "thread-continuity doctor",
            "thread-continuity mcp-config --mode installed",
        ],
        "safe_defaults": [
            "local-only index",
            "read-only source discovery",
            "no credential or browser local-storage reads",
            "no hosted sync",
        ],
    }


def _doctor_next_steps(checks: list[dict[str, Any]], index: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if not any(check["name"] == "cli_command" and check["ok"] for check in checks):
        steps.append("Install with `python3 -m pip install -e .` or use `python3 -m thread_continuity.cli` from the repo.")
    if not any(check["name"] == "mcp_command" and check["ok"] for check in checks):
        steps.append("After install, add the output of `thread-continuity mcp-config --mode installed` to your MCP client.")
    if not index.get("thread_count"):
        steps.append("Run `thread-continuity index` to build the local index.")
    if not steps:
        steps.append("Run `thread-continuity resume \"building X\"` or connect the MCP server to your agent client.")
    return steps


def _command_status(name: str, *, fallback_module: str) -> dict[str, Any]:
    found = shutil.which(name)
    if found:
        return {"ok": True, "detail": found}
    invoked = Path(sys.argv[0]).expanduser()
    if invoked.name == name and invoked.exists():
        return {"ok": True, "detail": str(invoked)}
    sibling = invoked.with_name(name)
    if sibling.exists():
        return {"ok": True, "detail": str(sibling)}
    return {"ok": False, "detail": f"not on PATH; use python3 -m {fallback_module}"}
