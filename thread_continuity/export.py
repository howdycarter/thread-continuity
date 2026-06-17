from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .utils import env_path, now_iso, stable_id


def default_export_path(thread_id: str, export_format: str) -> Path:
    ext = "html" if export_format == "html" else "md"
    safe_id = stable_id(thread_id)
    return env_path("THREAD_CONTINUITY_EXPORT_ROOT", "~/.codex/thread-continuity/exports") / f"{safe_id}.{ext}"


def render_pack(pack: dict[str, Any], *, export_format: str = "markdown") -> str:
    normalized = "html" if export_format == "html" else "markdown"
    if normalized == "html":
        return _render_html(pack)
    return _render_markdown(pack)


def write_pack(
    pack: dict[str, Any],
    *,
    export_format: str = "markdown",
    output_path: str | None = None,
) -> dict[str, Any]:
    normalized = "html" if export_format == "html" else "markdown"
    target = Path(output_path).expanduser() if output_path else default_export_path(pack["thread_id"], normalized)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_pack(pack, export_format=normalized)
    target.write_text(rendered, encoding="utf-8")
    return {
        "ok": True,
        "format": normalized,
        "output_path": str(target),
        "bytes": len(rendered.encode("utf-8")),
    }


def _render_markdown(pack: dict[str, Any]) -> str:
    lines = [
        f"# Thread Pack: {pack.get('title') or pack.get('thread_id')}",
        "",
        f"- Thread ID: `{pack.get('thread_id')}`",
        f"- Source: `{pack.get('source')}`",
        f"- Workspace: `{pack.get('workspace') or 'unknown'}`",
        f"- Status: `{pack.get('status')}`",
        f"- Updated: `{pack.get('updated_at') or 'unknown'}`",
        f"- Exported: `{now_iso()}`",
        "",
        "## Objective",
        "",
        pack.get("objective") or "Unknown.",
        "",
        "## Summary",
        "",
        pack.get("summary") or "No summary indexed.",
        "",
        "## Warnings",
        "",
    ]
    warnings = pack.get("warnings") or []
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- None")
    lines.extend(["", "## Evidence", ""])
    for item in pack.get("evidence") or []:
        lines.extend(
            [
                f"- `{item.get('role', 'unknown')}` from `{item.get('source_ref', 'unknown')}`",
                f"  - {item.get('snippet', '')}",
            ]
        )
    if not pack.get("evidence"):
        lines.append("- No matching evidence in compact pack.")
    return "\n".join(lines).rstrip() + "\n"


def _render_html(pack: dict[str, Any]) -> str:
    markdown = _render_markdown(pack)
    body = "\n".join(
        f"<p>{html.escape(line)}</p>" if line else ""
        for line in markdown.splitlines()
    )
    return (
        "<!doctype html>\n"
        "<html><head><meta charset=\"utf-8\"><title>Thread Pack</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:880px;margin:40px auto;line-height:1.5}"
        "p{white-space:pre-wrap}code{background:#f4f4f5;padding:0.1rem 0.25rem}</style>"
        "</head><body>"
        f"{body}"
        "</body></html>\n"
    )
