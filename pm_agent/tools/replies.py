"""Tools for reading owner replies."""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from ..core import replies
from .base import ToolContext, safe


def build(ctx: ToolContext) -> list:
    rt = ctx.rt

    @tool
    @safe
    def fetch_new_replies() -> list:
        """New, unprocessed replies from the agent mailbox and Google Chat DMs. Each has
        reply_id, channel, sender_email, sender_team_name, sender_in_team, received_at,
        subject, text, is_auto_reply, is_bounce. Call mark_reply_processed after each."""
        return replies.fetch_new_replies(rt)

    @tool
    @safe
    def mark_reply_processed(reply_id: str, sender_email: str, kind: str, summary: str,
                             task_ids: Optional[list[str]] = None) -> dict:
        """Mark a reply as handled so it is not processed again, and log it.
        kind: 'reply' (a person's reply; also stops today's pings for that sender),
        'auto_reply' (out-of-office), 'bounce', or 'not_for_this_project'."""
        return replies.mark_reply_processed(rt, reply_id, sender_email, kind, summary,
                                            task_ids or [])

    return [fetch_new_replies, mark_reply_processed]
