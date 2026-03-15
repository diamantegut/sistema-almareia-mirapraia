from __future__ import annotations

from typing import Any, Dict, List, Optional


def start_trace(*, enabled: bool, request_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "request": dict(request_context or {}),
        "steps": [],
        "finished": False,
    }


def record_step(trace_state: Dict[str, Any], *, step: str, input_data: Optional[Dict[str, Any]] = None, result: Optional[Dict[str, Any]] = None) -> None:
    if not bool((trace_state or {}).get("enabled")):
        return
    steps = trace_state.setdefault("steps", [])
    if isinstance(steps, list):
        steps.append(
            {
                "step": str(step or "").strip(),
                "input": dict(input_data or {}),
                "result": dict(result or {}),
            }
        )


def finish_trace(trace_state: Dict[str, Any], *, decision: str, reason_code: str) -> List[Dict[str, Any]]:
    if not bool((trace_state or {}).get("enabled")):
        return []
    record_step(
        trace_state,
        step="final_decision",
        input_data={},
        result={"decision": str(decision or "").strip().upper(), "reason_code": str(reason_code or "").strip()},
    )
    trace_state["finished"] = True
    steps = trace_state.get("steps")
    if isinstance(steps, list):
        return steps
    return []
