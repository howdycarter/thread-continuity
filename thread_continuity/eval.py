from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .utils import infer_intent


@dataclass(frozen=True)
class EvalCase:
    eval_id: str
    query: str
    expected_intent: str


DEFAULT_EVAL_CASES = [
    EvalCase("E001", "Resume building the OmniSocials queue review.", "resume_work"),
    EvalCase("E002", "Find the thread where we implemented Walter disclosure guards.", "find_implementation"),
    EvalCase("E003", "Where did we fix the metadata leak?", "find_implementation"),
    EvalCase("E004", "Continue the X bookmarks remix work.", "resume_work"),
    EvalCase("E005", "Find the thread that created the TestFlight checklist.", "find_artifact"),
    EvalCase("E006", "Where did we get SSH working to the MacBook Air?", "find_thread"),
    EvalCase("E007", "Which thread mentioned CASS or thread search?", "find_thread"),
    EvalCase("E008", "Resume auth bug.", "resume_work"),
    EvalCase("E009", "Find the production proof email.", "find_artifact"),
    EvalCase("E010", "Find work from a source whose body was unavailable.", "find_thread"),
]


def run_eval(api: Any, *, limit: int = 5, cases: list[EvalCase] | None = None) -> dict[str, Any]:
    selected = cases or DEFAULT_EVAL_CASES
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for case in selected:
        case_started = time.perf_counter()
        response = api.thread_search(case.query, limit=limit)
        elapsed_ms = round((time.perf_counter() - case_started) * 1000, 2)
        candidates = response.get("candidates", [])
        top = candidates[0] if candidates else None
        intent_ok = response.get("intent") == case.expected_intent or infer_intent(case.query) == case.expected_intent
        has_candidate = bool(candidates)
        citation_ok = bool(top and top.get("evidence"))
        results.append(
            {
                "eval_id": case.eval_id,
                "query": case.query,
                "expected_intent": case.expected_intent,
                "actual_intent": response.get("intent"),
                "passed": bool(intent_ok and has_candidate and citation_ok),
                "candidate_count": len(candidates),
                "top_thread_id": top.get("thread_id") if top else None,
                "top_confidence": top.get("confidence") if top else None,
                "top_status": top.get("status") if top else None,
                "warnings": response.get("warnings", []),
                "latency_ms": elapsed_ms,
            }
        )
    total_ms = round((time.perf_counter() - started) * 1000, 2)
    passed = sum(1 for item in results if item["passed"])
    return {
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 3) if results else 0,
        "total_latency_ms": total_ms,
        "p95_latency_ms": _p95([item["latency_ms"] for item in results]),
        "results": results,
        "notes": [
            "This is a local smoke eval, not the full PRD golden corpus.",
            "A pass means intent, at least one candidate, and cited evidence were returned.",
        ],
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return ordered[index]
