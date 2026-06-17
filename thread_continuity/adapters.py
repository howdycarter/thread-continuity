from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

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


def discover_claude_jsonl() -> list[Path]:
    root = env_path("CLAUDE_CODE_SESSION_ROOT", "~/.claude/projects")
    if not root.exists():
        return []
    return sorted(root.glob("**/*.jsonl"))


def discover_cursor_dbs() -> list[Path]:
    roots = [
        env_path("CURSOR_WORKSPACE_STORAGE_ROOT", "~/Library/Application Support/Cursor/User/workspaceStorage"),
        env_path("CURSOR_GLOBAL_STORAGE_ROOT", "~/Library/Application Support/Cursor/User/globalStorage"),
    ]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        paths.extend(sorted(root.glob("**/state.vscdb")))
        paths.extend(sorted(root.glob("**/*.sqlite")))
        paths.extend(sorted(root.glob("**/*.db")))
    return _dedupe_paths(paths)


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


def parse_cursor_composer(
    db_path: Path,
    composer_key: str,
    composer: dict[str, Any],
    workspace_by_composer: dict[str, str],
) -> ThreadRecord | None:
    composer_id = _string_or_none(composer.get("composerId")) or composer_key.split(":", 1)[-1]
    headers = composer.get("fullConversationHeadersOnly")
    if not isinstance(headers, list):
        return None

    messages: list[MessageRecord] = []
    participants: set[str] = set()
    bubble_map = _cursor_bubble_map(db_path, composer_id)
    for index, header in enumerate(headers, start=1):
        if not isinstance(header, dict):
            continue
        bubble_id = _string_or_none(header.get("bubbleId"))
        if not bubble_id:
            continue
        bubble = bubble_map.get(bubble_id)
        if not isinstance(bubble, dict):
            continue
        message = _message_from_cursor_bubble(db_path, composer_id, bubble_id, bubble, header, index)
        if message is None:
            continue
        participants.add(message.role)
        messages.append(message)

    if not messages:
        return None

    source_path = f"{db_path}#{composer_key}"
    workspace = workspace_by_composer.get(composer_id) or _first_workspace(messages)
    created_at = _cursor_timestamp(composer.get("createdAt")) or messages[0].timestamp
    updated_at = _cursor_timestamp(composer.get("lastUpdatedAt")) or messages[-1].timestamp or iso_from_mtime(db_path)
    title = _string_or_none(composer.get("name")) or _make_title(messages, db_path)
    full_text = "\n".join(message.text for message in messages[-80:])
    derived = _derive(messages, full_text)

    return ThreadRecord(
        thread_id="cursor-" + stable_id(f"{composer_id}:{db_path}"),
        source="cursor",
        workspace=workspace,
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        participants=sorted(participants) or ["unknown"],
        messages=messages,
        derived=derived,
        source_path=source_path,
        source_status="indexed",
        body_available=True,
    )


def parse_claude_jsonl(path: Path) -> ThreadRecord | None:
    metadata: dict[str, Any] = {}
    messages: list[MessageRecord] = []
    participants: set[str] = set()
    malformed = 0
    updated_at = iso_from_mtime(path)
    created_at: str | None = None
    workspace: str | None = None
    title: str | None = None

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line_number, line in enumerate(lines, start=1):
        item = safe_json_line(line)
        if item is None:
            malformed += 1
            continue
        session_id = _string_or_none(item.get("sessionId"))
        if session_id:
            metadata["sessionId"] = session_id
        timestamp = _string_or_none(item.get("timestamp"))
        if timestamp:
            updated_at = timestamp
            created_at = created_at or timestamp
        workspace = workspace or _string_or_none(item.get("cwd"))
        item_type = item.get("type")
        if item_type == "ai-title":
            title = _string_or_none(item.get("aiTitle")) or title
            continue
        parsed_messages = _messages_from_claude_item(path, line_number, item, timestamp)
        for message in parsed_messages:
            if not message.text:
                continue
            participants.add(message.role)
            messages.append(message)

    if not metadata and not messages:
        return None

    source_path = str(path)
    thread_id = "claude_code-" + stable_id(f"{metadata.get('sessionId') or path.stem}:{path}")
    full_text = "\n".join(message.text for message in messages[-80:])
    derived = _derive(messages, full_text)
    status = "indexed_with_warnings" if malformed else "indexed"

    return ThreadRecord(
        thread_id=thread_id,
        source="claude_code",
        workspace=workspace or _first_workspace(messages),
        title=title or _make_title(messages, path),
        created_at=created_at or (messages[0].timestamp if messages else updated_at),
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
    if source in {"all", "claude_code"}:
        for path in discover_claude_jsonl():
            record = parse_claude_jsonl(path)
            if record is None:
                continue
            yield record
            count += 1
            if max_threads is not None and count >= max_threads:
                return
    if source in {"all", "cursor"}:
        workspace_by_composer = _cursor_workspace_map()
        for db_path in discover_cursor_dbs():
            for composer_key, composer in _cursor_composers(db_path):
                record = parse_cursor_composer(db_path, composer_key, composer, workspace_by_composer)
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


def _messages_from_claude_item(
    path: Path,
    line_number: int,
    item: dict[str, Any],
    timestamp: str | None,
) -> list[MessageRecord]:
    item_type = str(item.get("type") or "")
    if item_type not in {"user", "assistant"}:
        return []
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    role = str(message.get("role") or item_type)
    content = message.get("content") if message else item.get("content")
    normal_parts: list[str] = []
    tool_messages: list[MessageRecord] = []

    if isinstance(content, str):
        normal_parts.append(content)
    elif isinstance(content, list):
        for part_index, part in enumerate(content):
            if isinstance(part, str):
                normal_parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "")
            if part_type == "text":
                text = _string_or_none(part.get("text"))
                if text:
                    normal_parts.append(text)
                continue
            if part_type == "tool_use":
                tool_name = _string_or_none(part.get("name")) or "tool"
                text = _claude_tool_use_text(tool_name, part.get("input"))
                tool_messages.append(
                    _record_message(
                        path,
                        line_number,
                        f"tool_use:{part_index}",
                        "tool",
                        text,
                        timestamp,
                        tool_name,
                    )
                )
                continue
            if part_type == "tool_result":
                text = _claude_tool_result_text(part.get("content"))
                if text:
                    tool_messages.append(
                        _record_message(
                            path,
                            line_number,
                            f"tool_result:{part_index}",
                            "tool",
                            text,
                            timestamp,
                            None,
                        )
                    )

    records: list[MessageRecord] = []
    normal_text = "\n".join(part for part in normal_parts if part.strip())
    if normal_text.strip():
        records.append(_record_message(path, line_number, "message", role, normal_text, timestamp, None))
    records.extend(tool_messages)
    return records


def _cursor_composers(db_path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    for key, raw_value in _cursor_rows(db_path, "cursorDiskKV", "composerData:%"):
        payload = _json_from_sqlite_value(raw_value)
        if isinstance(payload, dict):
            yield key, payload


def _cursor_bubble_map(db_path: Path, composer_id: str) -> dict[str, dict[str, Any]]:
    bubbles: dict[str, dict[str, Any]] = {}
    prefix = f"bubbleId:{composer_id}:"
    for key, raw_value in _cursor_rows(db_path, "cursorDiskKV", f"{prefix}%"):
        payload = _json_from_sqlite_value(raw_value)
        if not isinstance(payload, dict):
            continue
        bubble_id = key.removeprefix(prefix)
        if bubble_id:
            bubbles[bubble_id] = payload
    return bubbles


def _cursor_workspace_map() -> dict[str, str]:
    workspace_root = env_path("CURSOR_WORKSPACE_STORAGE_ROOT", "~/Library/Application Support/Cursor/User/workspaceStorage")
    mapping: dict[str, str] = {}
    if not workspace_root.exists():
        return mapping
    for storage_dir in sorted(path for path in workspace_root.iterdir() if path.is_dir()):
        workspace = _cursor_workspace_from_storage_dir(storage_dir)
        if not workspace:
            continue
        db_path = storage_dir / "state.vscdb"
        if not db_path.is_file():
            continue
        for _, raw_value in _cursor_rows(db_path, "ItemTable", "composer.composerData"):
            payload = _json_from_sqlite_value(raw_value)
            if not isinstance(payload, dict):
                continue
            for field in ("selectedComposerIds", "lastFocusedComposerIds"):
                ids = payload.get(field)
                if not isinstance(ids, list):
                    continue
                for composer_id in ids:
                    if isinstance(composer_id, str) and composer_id.strip():
                        mapping[composer_id] = workspace
    return mapping


def _cursor_workspace_from_storage_dir(storage_dir: Path) -> str | None:
    path = storage_dir / "workspace.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    folder = payload.get("folder") if isinstance(payload, dict) else None
    if not isinstance(folder, str) or not folder.strip():
        return None
    parsed = urlparse(folder)
    if parsed.scheme == "file":
        return unquote(parsed.path)
    return folder


def _cursor_rows(db_path: Path, table: str, key_like: str) -> Iterable[tuple[str, Any]]:
    if not db_path.is_file():
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    try:
        rows = conn.execute(f"SELECT key, value FROM {table} WHERE key LIKE ?", (key_like,))
        for key, value in rows:
            if isinstance(key, str):
                yield key, value
    except sqlite3.Error:
        return
    finally:
        conn.close()


def _message_from_cursor_bubble(
    db_path: Path,
    composer_id: str,
    bubble_id: str,
    bubble: dict[str, Any],
    header: dict[str, Any],
    index: int,
) -> MessageRecord | None:
    tool_data = bubble.get("toolFormerData") if isinstance(bubble.get("toolFormerData"), dict) else None
    role = "tool" if tool_data else ("user" if bubble.get("type") == 1 or header.get("type") == 1 else "assistant")
    tool_name = _string_or_none(tool_data.get("name")) if tool_data else None
    text = _cursor_tool_text(tool_name or "tool", tool_data) if tool_data else _string_or_none(bubble.get("text"))
    if not text:
        return None
    timestamp = _cursor_timestamp(bubble.get("createdAt"))
    line_ref = f"{db_path}#bubbleId:{composer_id}:{bubble_id}"
    return _record_message(
        Path(str(db_path)),
        index,
        f"cursor:{composer_id}:{bubble_id}",
        role,
        text,
        timestamp,
        tool_name,
        line_ref=line_ref,
    )


def _cursor_tool_text(tool_name: str, tool_data: dict[str, Any] | None) -> str:
    if not tool_data:
        return ""
    parts = [f"{tool_name}:"]
    for field in ("rawArgs", "params", "result", "error"):
        value = tool_data.get(field)
        if value is None:
            continue
        rendered = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        if rendered.strip():
            parts.append(f"{field}: {rendered}")
    return "\n".join(parts)


def _json_from_sqlite_value(raw_value: Any) -> Any | None:
    if isinstance(raw_value, bytes):
        text = raw_value.decode("utf-8", errors="replace")
    elif isinstance(raw_value, str):
        text = raw_value
    else:
        return None
    return parse_json(text)


def _cursor_timestamp(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=0).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return _string_or_none(value)


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


def _record_message(
    path: Path,
    line_number: int,
    suffix: str,
    role: str,
    text: str,
    timestamp: str | None,
    tool_name: str | None,
    line_ref: str | None = None,
) -> MessageRecord:
    clipped = compact_text(text, limit=8000)
    return MessageRecord(
        message_id=stable_id(f"{path}:{line_number}:{suffix}:{role}:{clipped[:120]}"),
        role=role,
        text=clipped,
        timestamp=timestamp,
        tool_name=tool_name,
        artifacts=extract_artifacts(clipped),
        line_ref=line_ref or f"{path}:{line_number}",
    )


def _claude_tool_use_text(tool_name: str, raw_input: Any) -> str:
    rendered = json.dumps(raw_input, sort_keys=True) if isinstance(raw_input, (dict, list)) else str(raw_input or "")
    parsed = parse_json(rendered)
    if isinstance(parsed, dict) and "command" in parsed:
        return f"{tool_name}: {parsed.get('command')}"
    if isinstance(parsed, dict) and "cmd" in parsed:
        return f"{tool_name}: {parsed.get('cmd')}"
    return f"{tool_name}: {rendered}"


def _claude_tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _content_text(content)
    if isinstance(content, dict):
        return json.dumps(content, sort_keys=True)
    return ""


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


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result
