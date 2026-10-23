"""Read-only plan views used by the Reminder, Monitoring and Data Quality agents."""
from __future__ import annotations

from langchain_core.tools import tool

from ..core import planning
from .base import ToolContext, safe


def build(ctx: ToolContext) -> list:
    rt = ctx.rt

    @tool
    @safe
    def get_assignment_plan() -> list:
        """Owners who need an assignment email today, with their tasks (sent on any day)."""
        return planning.assignment_plan(rt)

    @tool
    @safe
    def get_daily_request_plan() -> dict:
        """Combined daily update requests per owner for today, overdue tasks first.
        Already excludes owners on leave and owners asked earlier today."""
        return planning.daily_request_plan(rt)

    @tool
    @safe
    def get_owners_awaiting_reply() -> list:
        """Owners who got today's daily request and have not replied on any channel,
        with their task IDs, pings already sent today and leave status."""
        return planning.owners_awaiting_reply(rt)

    @tool
    @safe
    def get_data_issues() -> dict:
        """Plan problems to report to the alert recipient (owner problems, unreadable
        dates, leave clashes, tab conflicts) and plan date changes since the last run."""
        return planning.data_issue_report(rt)

    @tool
    @safe
    def find_stalled_tasks() -> dict:
        """In Progress tasks whose % Complete has not increased for 2+ working days, with
        full notes (check them for a valid reason first) and each task's alert recipient.
        Also tasks that recovered since the previous working day."""
        return planning.find_stalled(rt)

    @tool
    @safe
    def find_long_stuck_tasks() -> dict:
        """Tasks On Hold, Blocked or without an update for more than 7 working days, not
        yet escalated today, and the Program Manager Head to send them to."""
        return planning.find_long_stuck(rt)

    @tool
    @safe
    def get_pre_delivery_status() -> dict:
        """Whether today is in the 15-day pre-delivery window, the Blocked and On Hold
        items, the recipients, and whether the email or the chat fallback is due."""
        return planning.pre_delivery_status(rt)

    return [get_assignment_plan, get_daily_request_plan, get_owners_awaiting_reply,
            get_data_issues, find_stalled_tasks, find_long_stuck_tasks, get_pre_delivery_status]
