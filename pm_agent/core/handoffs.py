"""Hand-offs between agents.

The Reply Agent does not handle blockers itself. When a reply reports a block
(or a cleared block), it files a hand-off here, and the Blocker Agent picks it
up in the same run. Hand-offs are kept in the state file, so one that was filed
just before a crash is still handled on the next run.
"""
from __future__ import annotations

import uuid
from typing import Optional

from .runtime import Runtime


def add_handoff(rt: Runtime, to_agent: str, kind: str, task_id: str, reported_by: str,
                sender_email: str, channel: str, details: str,
                blocking_hint: Optional[str] = None) -> dict:
    h = {"id": uuid.uuid4().hex[:8], "to_agent": to_agent, "kind": kind, "task_id": task_id,
         "reported_by": reported_by, "sender_email": sender_email, "channel": channel,
         "details": details, "blocking_hint": blocking_hint,
         "created_at": rt.now().isoformat(), "done_at": None, "outcome": None}
    rt.state.data["handoffs"].append(h)
    rt.state.save()
    return {"handed_off": True, "handoff_id": h["id"]}


def pending_handoffs(rt: Runtime, to_agent: str) -> list[dict]:
    return [h for h in rt.state.data["handoffs"]
            if h["to_agent"] == to_agent and not h["done_at"]]


def complete_handoff(rt: Runtime, handoff_id: str, outcome: str) -> dict:
    for h in rt.state.data["handoffs"]:
        if h["id"] == handoff_id:
            h["done_at"], h["outcome"] = rt.now().isoformat(), outcome
            rt.state.save()
            return {"completed": True}
    return {"error": f"No hand-off {handoff_id}"}
