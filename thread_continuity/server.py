from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .api import ThreadContinuity


JsonDict = dict[str, Any]


TOOLS: dict[str, dict[str, Any]] = {
    "thread_triage": {
        "description": "Inspect local source readiness, CASS availability, and index status.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "thread_sources_status": {
        "description": "Alias for source readiness status required by the PRD.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "thread_sources_add": {
        "description": "Register a read-only local source profile for future indexing support.",
        "inputSchema": {
            "type": "object",
            "required": ["path_or_profile", "source_type"],
            "properties": {
                "path_or_profile": {"type": "string"},
                "source_type": {
                    "type": "string",
                    "enum": ["codex", "memory", "claude_code", "cursor", "cass", "other"],
                },
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "thread_index_status": {
        "description": "Return current local SQLite index status.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "thread_index": {
        "description": "Index local sources read-only into SQLite.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {"type": "boolean"},
                "source": {"type": "string", "enum": ["all", "codex", "memory"]},
                "max_threads": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
    },
    "thread_search": {
        "description": "Search local thread history and return ranked candidates with evidence.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "workspace": {"type": "string"},
                "source": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "mode": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "thread_resume": {
        "description": "Find continuation candidates and return last state plus next best action.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "workspace": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "additionalProperties": False,
        },
    },
    "thread_pack": {
        "description": "Build a compact continuation packet for a known thread id.",
        "inputSchema": {
            "type": "object",
            "required": ["thread_id"],
            "properties": {
                "thread_id": {"type": "string"},
                "focus": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "thread_export": {
        "description": "Export a compact thread pack as Markdown or HTML.",
        "inputSchema": {
            "type": "object",
            "required": ["thread_id"],
            "properties": {
                "thread_id": {"type": "string"},
                "focus": {"type": "string"},
                "format": {"type": "string", "enum": ["markdown", "html"]},
                "output_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "thread_get": {
        "description": "Fetch indexed thread metadata, optionally including messages.",
        "inputSchema": {
            "type": "object",
            "required": ["thread_id"],
            "properties": {
                "thread_id": {"type": "string"},
                "include_messages": {"type": "boolean"},
                "include_outputs": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    "thread_sources_list": {
        "description": "List configured source adapters and their availability.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "thread_open_ref": {
        "description": "Return the best local reference for opening a thread in the host.",
        "inputSchema": {
            "type": "object",
            "required": ["thread_id"],
            "properties": {"thread_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "thread_eval": {
        "description": "Run the local smoke eval suite from the PRD query set.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            "additionalProperties": False,
        },
    },
    "thread_explain_result": {
        "description": "Explain the ranking inputs for a result id returned by search.",
        "inputSchema": {
            "type": "object",
            "required": ["result_id"],
            "properties": {"result_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
}


def main() -> None:
    api = ThreadContinuity()
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = handle_request(api, request)
            except Exception as exc:  # Keep MCP failures structured.
                response = _error(None, -32603, f"{exc.__class__.__name__}: {exc}")
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
    finally:
        api.close()


def handle_request(api: ThreadContinuity, request: JsonDict) -> JsonDict | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "thread-continuity", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(
            request_id,
            {
                "tools": [
                    {"name": name, **metadata}
                    for name, metadata in sorted(TOOLS.items(), key=lambda item: item[0])
                ]
            },
        )
    if method == "tools/call":
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name not in TOOLS:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        result = _call_tool(api, str(name), arguments)
        return _result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, sort_keys=True),
                    }
                ],
                "isError": False,
            },
        )
    return _error(request_id, -32601, f"Method not found: {method}")


def _call_tool(api: ThreadContinuity, name: str, arguments: JsonDict) -> JsonDict:
    dispatch: dict[str, Callable[..., JsonDict]] = {
        "thread_triage": api.thread_triage,
        "thread_index": api.thread_index,
        "thread_search": api.thread_search,
        "thread_resume": api.thread_resume,
        "thread_pack": api.thread_pack,
        "thread_export": api.thread_export,
        "thread_get": api.thread_get,
        "thread_sources_list": api.thread_sources_list,
        "thread_sources_status": api.thread_sources_status,
        "thread_sources_add": api.thread_sources_add,
        "thread_index_status": api.thread_index_status,
        "thread_open_ref": api.thread_open_ref,
        "thread_eval": api.thread_eval,
        "thread_explain_result": api.thread_explain_result,
    }
    return dispatch[name](**arguments)


def _result(request_id: Any, result: JsonDict) -> JsonDict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> JsonDict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
