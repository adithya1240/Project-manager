"""Email and Google Chat tools. Each agent may only send its own action types."""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from ..core import messaging
from .base import ToolContext, safe


def build(ctx: ToolContext) -> list:
    rt = ctx.rt
    allowed = sorted(ctx.send_actions)

    def not_allowed(action_type: str) -> Optional[dict]:
        if action_type not in ctx.send_actions:
            return {"error": f"{ctx.agent_name} may only send these action types: {allowed}."}
        return None

    @tool
    @safe
    def send_email(to: list[str], subject: str, body: str, action_type: str,
                   task_ids: Optional[list[str]] = None, cc: Optional[list[str]] = None,
                   reply_to_id: Optional[str] = None, summary: str = "") -> dict:
        """Send a plain-text email from the agent mailbox to Team tab addresses only.
        action_type is the Activity Log action type (only those your role allows).
        task_ids: the tasks it covers (one log row each). reply_to_id: a 'gmail:' reply id
        to answer in the same thread (subject may then be empty). Refused with a reason if
        it would repeat today's send or break a timing rule; logged automatically."""
        return not_allowed(action_type) or messaging.send_email(
            rt, to, subject, body, action_type, task_ids or [], cc or [], reply_to_id, summary)

    @tool
    @safe
    def send_chat(to: str, text: str, action_type: str,
                  task_ids: Optional[list[str]] = None, summary: str = "") -> dict:
        """Send a Google Chat direct message to one Team tab email. Same checks and
        logging as send_email."""
        return not_allowed(action_type) or messaging.send_chat(
            rt, to, text, action_type, task_ids or [], summary)

    return [send_email, send_chat]
