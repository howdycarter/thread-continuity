from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import default_config_path, env_path, now_iso, stable_id


SUPPORTED_SOURCE_TYPES = {
    "codex",
    "memory",
    "claude_code",
    "cursor",
    "cass",
    "other",
}


def load_profiles(config_path: Path | None = None) -> list[dict[str, Any]]:
    path = config_path or default_config_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    profiles = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(profiles, list):
        return []
    return [profile for profile in profiles if isinstance(profile, dict)]


def add_profile(
    *,
    path_or_profile: str,
    source_type: str,
    name: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    normalized_type = source_type.strip().lower()
    if normalized_type not in SUPPORTED_SOURCE_TYPES:
        return {
            "ok": False,
            "error": f"unsupported source_type: {source_type}",
            "supported_source_types": sorted(SUPPORTED_SOURCE_TYPES),
        }
    path = config_path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    profiles = load_profiles(path)
    expanded = str(Path(path_or_profile).expanduser()) if path_or_profile else ""
    profile_id = stable_id(f"{normalized_type}:{expanded}:{name or ''}")
    profile = {
        "id": profile_id,
        "name": name or f"{normalized_type}:{Path(expanded).name or expanded}",
        "source_type": normalized_type,
        "path": expanded,
        "added_at": now_iso(),
        "read_only": True,
    }
    profiles = [existing for existing in profiles if existing.get("id") != profile_id]
    profiles.append(profile)
    path.write_text(json.dumps({"sources": profiles}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "profile": profile, "config_path": str(path)}


def configured_source_status() -> list[dict[str, Any]]:
    statuses = []
    for profile in load_profiles():
        raw_path = profile.get("path")
        candidate = Path(raw_path).expanduser() if isinstance(raw_path, str) else None
        statuses.append(
            {
                "source": profile.get("source_type", "other"),
                "kind": "configured-profile",
                "name": profile.get("name"),
                "profile_id": profile.get("id"),
                "path": str(candidate) if candidate else raw_path,
                "available": bool(candidate and candidate.exists()),
                "read_only": True,
                "note": "registered profile; indexing requires a matching adapter",
            }
        )
    return statuses


def harness_source_status() -> list[dict[str, Any]]:
    claude_root = env_path("CLAUDE_CODE_SESSION_ROOT", "~/.claude/projects")
    cursor_roots = [
        env_path("CURSOR_WORKSPACE_STORAGE_ROOT", "~/Library/Application Support/Cursor/User/workspaceStorage"),
        env_path("CURSOR_GLOBAL_STORAGE_ROOT", "~/Library/Application Support/Cursor/User/globalStorage"),
    ]
    return [
        {
            "source": "claude_code",
            "kind": "jsonl",
            "available": claude_root.is_dir(),
            "count": _count_files(claude_root, "*.jsonl") if claude_root.is_dir() else 0,
            "paths": [str(claude_root)],
            "read_only": True,
            "indexing": "enabled",
            "note": "Claude Code JSONL parser enabled for local read-only indexing",
        },
        {
            "source": "cursor",
            "kind": "sqlite-or-json-storage",
            "available": any(root.exists() for root in cursor_roots),
            "count": sum(_count_files(root, "*.sqlite") + _count_files(root, "*.db") for root in cursor_roots if root.exists()),
            "paths": [str(root) for root in cursor_roots],
            "read_only": True,
            "indexing": "not_implemented",
            "note": "detected for Phase 2; avoids browser/local-storage credential surfaces",
        },
    ]


def _count_files(root: Path, pattern: str) -> int:
    try:
        return sum(1 for _ in root.glob(f"**/{pattern}"))
    except OSError:
        return 0
