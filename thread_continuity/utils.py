from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


URL_RE = re.compile(r"https?://[^\s)>\]]+")
PATH_RE = re.compile(
    r"(?:/Users/[^\s)>\]]+|/Volumes/[^\s)>\]]+|(?:[\w.-]+/)+[\w.@-]+(?:\.[A-Za-z0-9]+)?)"
)
SPACE_RE = re.compile(r"\s+")
SECRET_REPLACEMENTS = [
    (re.compile(r"(?i)(password=)[^&\s)>\]]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|client_secret)=)[^&\s)>\]]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "sk-<redacted>"),
    (re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b"), "gh_<redacted>"),
]
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "client_secret",
    "key",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


def default_db_path() -> Path:
    return env_path("THREAD_CONTINUITY_DB", "~/.codex/thread-continuity/index.sqlite3")


def default_config_path() -> Path:
    return env_path("THREAD_CONTINUITY_CONFIG", "~/.codex/thread-continuity/sources.json")


def compact_text(text: str, *, limit: int = 280) -> str:
    clean = SPACE_RE.sub(" ", redact_text(text)).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def parse_json(value: str) -> Any | None:
    try:
        return json.loads(value)
    except Exception:
        return None


def safe_json_line(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def extract_artifacts(text: str) -> list[str]:
    found: list[str] = []
    for pattern in (URL_RE, PATH_RE):
        for match in pattern.findall(text):
            token = sanitize_artifact(match.rstrip(".,;:'\""))
            if token not in found:
                found.append(token)
    return found[:20]


def redact_text(text: str) -> str:
    redacted = text
    for pattern, replacement in SECRET_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def sanitize_artifact(value: str) -> str:
    cleaned = redact_text(value)
    if not cleaned.startswith(("http://", "https://")):
        return cleaned
    try:
        parts = urlsplit(cleaned)
    except ValueError:
        return cleaned
    query_pairs = []
    for key, raw_value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS:
            query_pairs.append((key, "<redacted>"))
        else:
            query_pairs.append((key, raw_value))
    # Drop fragments and keep a redacted query only when it carries non-secret meaning.
    query = urlencode(query_pairs) if query_pairs else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def sanitize_value(value: Any, *, list_limit: int = 12) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [sanitize_value(item, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, dict):
        return {key: sanitize_value(item, list_limit=list_limit) for key, item in value.items()}
    return value


def infer_intent(query: str) -> str:
    q = query.lower()
    if any(word in q for word in ("resume", "continue", "pick up", "restart")):
        return "resume_work"
    if "decision" in q or "decided" in q:
        return "find_decision"
    if "blocker" in q or "blocked" in q or "stuck" in q:
        return "find_blocker"
    if any(word in q for word in ("artifact", "file", "doc", "path", "url", "proof", "checklist")):
        return "find_artifact"
    if any(word in q for word in ("implemented", "implementation", "built", "fix", "fixed", "coded")):
        return "find_implementation"
    if any(word in q for word in ("health", "status", "state")):
        return "health_or_status"
    return "find_thread"


def classify_outcome(text: str) -> str:
    q = text.lower()
    if any(word in q for word in ("blocked", "blocker", "cannot proceed", "stuck")):
        return "blocked"
    if any(word in q for word in ("partial", "in progress", "remaining", "not complete")):
        return "partial"
    if any(word in q for word in ("complete", "done", "passed", "verified", "merged")):
        return "done"
    return "unknown"


def cass_status() -> dict[str, Any]:
    path = shutil.which("cass")
    return {
        "available": path is not None,
        "path": path,
        "note": "cass not found; using Codex-native fallback indexer" if path is None else "cass available",
    }


def iso_from_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return None


def days_old(updated_at: str | None) -> int | None:
    if not updated_at:
        return None
    normalized = updated_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return max(0, delta.days)
