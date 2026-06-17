from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import DerivedRecord, MessageRecord, ThreadRecord
from .sources import configured_source_status, harness_source_status
from .utils import (
    classify_outcome,
    compact_text,
    env_path,
    extract_artifacts,
    iso_from_mtime,
    parse_json,
    safe_json_line,
    stable_id,
)


def discover_codex_jsonl() -> list[Path]:
    roots = [
        env_path("CODEX_SESSION_ROOT", "~/.codex/sessions"),
        env_path("CODEX_ARCHIVED_SESSION_ROOT", "~/.codex/archived_sessions"),
    ]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        paths.extend(sorted(root.glob("**/*.jsonl")))
    return paths


def discover_memory_files() -> list[Path]:
    root = env_path("CODEX_MEMORY_ROOT", "~/.codex/memories")
    paths: list[Path] = []
    memory_index = root / "MEMORY.md"
    if memory_index.is_file():
        paths.append(memory_index)
    summaries = root / "rollout_summaries"
    if summaries.is_dir():
        paths.extend(sorted(summaries.glob("*.md"))[:200])
        paths.extend(sorted(summaries.glob("*.jsonl"))[:200])
    return paths


def parse_codex_jsonl(path: Path) -> ThreadRecord | None:
    metadata: dict[str, Any] = {}
    messages: list[MessageRecord] = []
    participants: set[str] = set()
    malformed = 0
    updated_at = iso_from_mtime(path)

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line_number, line in enumerate(lines, start=1):
        item = safe_json_line(line)
        if item is None:
            malformed += 1
            continue
        timestamp = item.get("timestamp")
        if isinstance(timestamp, str):
            updated_at = timestamp
        item_type = item.get("type")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if item_type == "session_meta":
            metadata.update(payload)
            continue
        message = _message_from_item(path, line_number, item_type, payload, timestamp)
        if message is None or not message.text:
            continue
        if message.role in {"system", "developer"}:
            continue
        participants.add(message.role)
        messages.append(message)

    if not metadata and not messages:
        return None

    source_path = str(path)
    thread_id = str(metadata.get("id") or _thread_id_from_path(path))
    workspace = _string_or_none(metadata.get("cwd")) or _first_workspace(messages)
    created_at = _string_or_none(metadata.get("timestamp")) or (messages[0].timestamp if messages else updated_at)
    title = _make_title(messages, path)
    full_text = "\n".join(message.text for message in messages[-80:])
    derived = _derive(messages, full_text)
    status = "indexed_with_warnings" if malformed else "indexed"

    return ThreadRecord(
        thread_id=thread_id,
        source="codex",
        workspace=workspace,
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        participants=sorted(participants) or ["unknown"],
        messages=messages,
        derived=derived,
        source_path=source_path,
        source_status=status,
        body_available=bool(messages),
    )


def parse_memory_file(path: Path) -> ThreadRecord | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.strip():
        return None
    thread_id = "memory-" + stable_id(str(path))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = path.stem.replace("_", " ").replace("-", " ")
    messages = [
        MessageRecord(
            message_id=f"{thread_id}-memory",
            role="tool",
            text=compact_text("\n".join(lines[:80]), limit=3000),
            timestamp=iso_from_mtime(path),
            artifacts=extract_artifacts(text),
            line_ref=f"{path}:1",
        )
    ]
    return ThreadRecord(
        thread_id=thread_id,
        source="memory",
        workspace=None,
        title=title,
        created_at=iso_from_mtime(path),
        updated_at=iso_from_mtime(path),
        participants=["tool"],
        messages=messages,
        derived=DerivedRecord(
            summary=compact_text(lines[0] if lines else title),
            outcome="unknown",
            proof_links=extract_artifacts(text),
        ),
        source_path=str(path),
        source_status="metadata_only",
        body_available=True,
    )


def iter_records(source: str = "all", max_threads: int | None = None) -> Iterable[ThreadRecord]:
    count = 0
    if source in {"all", "codex"}:
        for path in discover_codex_jsonl():
            record = parse_codex_jsonl(path)
            if record is None:
                continue
            yield record
            count += 1
            if max_threads is not None and count >= max_threads:
                return
    if source in {"all", "memory"}:
        for path in discover_memory_files():
            record = parse_memory_file(path)
            if record is None:
                continue
            yield record
            count += 1
            if max_threads is not None and count >= max_threads:
                return


def source_status() -> list[dict[str, Any]]:
    codex_paths = discover_codex_jsonl()
    memory_paths = discover_memory_files()
    statuses = [
        {
            "source": "codex",
            "kind": "jsonl",
            "available": bool(codex_paths),
            "count": len(codex_paths),
            "paths": _roots_status(["CODEX_SESSION_ROOT", "CODEX_ARCHIVED_SESSION_ROOT"]),
        },
        {
            "source": "memory",
            "kind": "markdown",
            "available": bool(memory_paths),
            "count": len(memory_paths),
            "paths": _roots_status(["CODEX_MEMORY_ROOT"]),
        },
    ]
    statuses.extend(harness_source_status())
    statuses.extend(configured_source_status())
    return statuses


def _roots_status(names: list[str]) -> list[str]:
    defaults = {
        "CODEX_SESSION_ROOT": "~/.codex/sessions",
        "CODEX_ARCHIVED_SESSION_ROOT": "~/.codex/archived_sessions",
        "CODEX_MEMORY_ROOT": "~/.codex/memories",
    }
    return [str(env_path(name, defaults[name])) for name in names]


def _message_from_item(
    path: Path,
    line_number: int,
    item_type: Any,
    payload: dict[str, Any],
    timestamp: Any,
) -> MessageRecord | None:
    role = "tool"
    text = ""
    tool_name = None
    if item_type == "response_item":
        payload_type = payload.get("type")
        if payload_type == "message":
            role = str(payload.get("role") or "assistant")
            text = _content_text(payload.get("content"))
        elif payload_type == "function_call":
            role = "tool"
            tool_name = _string_or_none(payload.get("name"))
            text = _function_call_text(payload)
        elif payload_type == "function_call_output":
            role = "tool"
            text = _string_or_none(payload.get("output")) or ""
        else:
            return None
    elif item_type == "event_msg":
        event_type = str(payload.get("type") or "")
        if event_type == "user_message":
            role = "user"
            text = _string_or_none(payload.get("message")) or ""
        elif event_type == "agent_message":
            role = "assistant"
            text = _string_or_none(payload.get("message")) or ""
        else:
            return None
    else:
        return None

    if not text.strip():
        return None
    message_id = stable_id(f"{path}:{line_number}:{role}:{text[:80]}")
    return MessageRecord(
        message_id=message_id,
        role=role,
        text=text,
        timestamp=_string_or_none(timestamp),
        tool_name=tool_name,
        artifacts=extract_artifacts(text),
        line_ref=f"{path}:{line_number}",
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _function_call_text(payload: dict[str, Any]) -> str:
    name = _string_or_none(payload.get("name")) or "tool"
    raw_args = payload.get("arguments")
    rendered = raw_args if isinstance(raw_args, str) else json.dumps(raw_args, sort_keys=True)
    parsed = parse_json(rendered)
    if isinstance(parsed, dict) and "cmd" in parsed:
        return f"{name}: {parsed.get('cmd')}"
    return f"{name}: {rendered}"


def _derive(messages: list[MessageRecord], full_text: str) -> DerivedRecord:
    user_messages = [message.text for message in messages if message.role == "user"]
    assistant_messages = [message.text for message in messages if message.role == "assistant"]
    objective = compact_text(user_messages[0], limit=220) if user_messages else None
    summary_source = assistant_messages[-1] if assistant_messages else (user_messages[0] if user_messages else "")
    artifacts: list[str] = []
    commands: list[str] = []
    blockers: list[str] = []
    next_steps: list[str] = []
    for message in messages:
        for artifact in message.artifacts:
            if artifact not in artifacts:
                artifacts.append(artifact)
        if message.tool_name in {"exec_command", "shell"} or message.text.startswith("exec_command:"):
            commands.append(compact_text(message.text, limit=220))
        lowered = message.text.lower()
        if "blocked" in lowered or "blocker" in lowered:
            blockers.append(compact_text(message.text, limit=220))
        if "next" in lowered or "remaining" in lowered:
            next_steps.append(compact_text(message.text, limit=220))
    return DerivedRecord(
        summary=compact_text(summary_source, limit=320),
        objective=objective,
        outcome=classify_outcome(full_text),
        files_touched=[artifact for artifact in artifacts if not artifact.startswith("http")][:30],
        commands_run=commands[-30:],
        proof_links=[artifact for artifact in artifacts if artifact.startswith("http")][:30],
        blockers=blockers[-10:],
        next_steps=next_steps[-10:],
    )


def _make_title(messages: list[MessageRecord], path: Path) -> str:
    for message in messages:
        if message.role == "user" and message.text.strip():
            first = message.text.strip().splitlines()[0]
            return compact_text(first, limit=120)
    return path.stem


def _thread_id_from_path(path: Path) -> str:
    stem = path.stem
    if "rollout-" in stem:
        maybe_id = stem.split("-")[-5:]
        if len(maybe_id) == 5:
            return "-".join(maybe_id)
    return stable_id(str(path))


def _first_workspace(messages: list[MessageRecord]) -> str | None:
    for message in messages[:20]:
        for artifact in message.artifacts:
            if artifact.startswith("/Users/") or artifact.startswith("/Volumes/"):
                return artifact
    return None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
