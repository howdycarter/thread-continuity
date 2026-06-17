from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MessageRecord:
    message_id: str
    role: str
    text: str
    timestamp: str | None = None
    tool_name: str | None = None
    artifacts: list[str] = field(default_factory=list)
    line_ref: str | None = None


@dataclass
class DerivedRecord:
    summary: str = ""
    objective: str | None = None
    outcome: str = "unknown"
    files_touched: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    proof_links: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


@dataclass
class ThreadRecord:
    thread_id: str
    source: str
    workspace: str | None
    title: str
    created_at: str | None
    updated_at: str | None
    participants: list[str]
    messages: list[MessageRecord]
    derived: DerivedRecord
    source_path: str
    source_status: str = "indexed"
    body_available: bool = True

