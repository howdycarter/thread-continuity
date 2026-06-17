from __future__ import annotations

import argparse
import json
from typing import Any

from .api import ThreadContinuity
from .bootstrap import doctor, install_notes, mcp_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Thread Continuity local CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("triage")
    sub.add_parser("doctor")
    sub.add_parser("install-notes")
    sub.add_parser("sources")
    sub.add_parser("index-status")

    mcp = sub.add_parser("mcp-config")
    mcp.add_argument("--mode", choices=["installed", "source"], default="installed")
    mcp.add_argument("--cwd")

    source_add = sub.add_parser("source-add")
    source_add.add_argument("path_or_profile")
    source_add.add_argument("source_type")
    source_add.add_argument("--name")

    index = sub.add_parser("index")
    index.add_argument("--force", action="store_true")
    index.add_argument("--source", default="all")
    index.add_argument("--max-threads", type=int, default=None)

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--workspace")
    search.add_argument("--source")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--mode")

    resume = sub.add_parser("resume")
    resume.add_argument("query")
    resume.add_argument("--workspace")
    resume.add_argument("--limit", type=int, default=5)

    pack = sub.add_parser("pack")
    pack.add_argument("thread_id")
    pack.add_argument("--focus")

    export = sub.add_parser("export")
    export.add_argument("thread_id")
    export.add_argument("--focus")
    export.add_argument("--format", choices=["markdown", "html"], default="markdown")
    export.add_argument("--output-path")

    open_ref = sub.add_parser("open-ref")
    open_ref.add_argument("thread_id")

    eval_parser = sub.add_parser("eval")
    eval_parser.add_argument("--limit", type=int, default=5)

    get = sub.add_parser("get")
    get.add_argument("thread_id")
    get.add_argument("--include-messages", action="store_true")
    get.add_argument("--include-outputs", action="store_true")

    args = parser.parse_args()
    api = ThreadContinuity()
    try:
        result = _dispatch(api, args)
    finally:
        api.close()
    print(json.dumps(result, indent=2, sort_keys=True))


def _dispatch(api: ThreadContinuity, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "triage":
        return api.thread_triage()
    if args.command == "doctor":
        return doctor()
    if args.command == "install-notes":
        return install_notes()
    if args.command == "mcp-config":
        return mcp_config(mode=args.mode, cwd=args.cwd)
    if args.command == "sources":
        return api.thread_sources_status()
    if args.command == "index-status":
        return api.thread_index_status()
    if args.command == "source-add":
        return api.thread_sources_add(
            path_or_profile=args.path_or_profile,
            source_type=args.source_type,
            name=args.name,
        )
    if args.command == "index":
        return api.thread_index(force=args.force, source=args.source, max_threads=args.max_threads)
    if args.command == "search":
        return api.thread_search(
            args.query,
            workspace=args.workspace,
            source=args.source,
            limit=args.limit,
            mode=args.mode,
        )
    if args.command == "resume":
        return api.thread_resume(args.query, workspace=args.workspace, limit=args.limit)
    if args.command == "pack":
        return api.thread_pack(args.thread_id, focus=args.focus)
    if args.command == "export":
        return api.thread_export(
            args.thread_id,
            focus=args.focus,
            format=args.format,
            output_path=args.output_path,
        )
    if args.command == "open-ref":
        return api.thread_open_ref(args.thread_id)
    if args.command == "eval":
        return api.thread_eval(limit=args.limit)
    if args.command == "get":
        return api.thread_get(
            args.thread_id,
            include_messages=args.include_messages,
            include_outputs=args.include_outputs,
        )
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
