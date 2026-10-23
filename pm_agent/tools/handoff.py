"""Hand-off tools: the Reply Agent files blocker reports, the Blocker Agent works them."""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from ..core import handoffs
from .base import ToolContext, safe

BLOCKER_AGENT = "blocker_agent"


def build(ctx: ToolContext) -> list:
    rt = ctx.rt

    @tool
    @safe
    def hand_off_to_blocker_agent(task_id: str, kind: str, reported_by: str,
                                  sender_email: str, channel: str, details: str,
                                  blocking_hint: Optional[str] = None) -> dict:
        """Pass a blocker report to the Blocker Agent, which acts on it straight after you.
        kind: 'blocked' or 'cleared'. details: what the owner said, in their words.
        blocking_hint: the task ID or person the owner named as the blocker, if any."""
        if kind not in ("blocked", "cleared"):
            return {"error": "kind must be 'blocked' or 'cleared'"}
        return handoffs.add_handoff(rt, BLOCKER_AGENT, kind, task_id, reported_by,
                                    sender_email, channel, details, blocking_hint)

    @tool
    @safe
    def get_blocker_handoffs() -> list:
        """Blocker reports waiting for you, filed by the Reply Agent."""
        return handoffs.pending_handoffs(rt, BLOCKER_AGENT)

    @tool
    @safe
    def complete_blocker_handoff(handoff_id: str, outcome: str) -> dict:
        """Mark a blocker hand-off as done, with a one-line outcome."""
        return handoffs.complete_handoff(rt, handoff_id, outcome)

    return [hand_off_to_blocker_agent, get_blocker_handoffs, complete_blocker_handoff]
