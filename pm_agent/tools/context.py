"""Read-only context tools, plus the general activity-log writer."""
from __future__ import annotations

from datetime import timedelta

from langchain_core.tools import tool

from ..config import CLOSED
from ..core import planning
from .base import ToolContext, safe


def build(ctx: ToolContext) -> list:
    rt = ctx.rt

    @tool
    @safe
    def get_run_context() -> dict:
        """Current IST time, whether today is a working day, who is on leave, who receives
        alerts today (PM or Program Manager Head) and the Team tab. Call this first."""
        return planning.run_context(rt)

    @tool
    @safe
    def read_project_plan(include_closed: bool = False) -> dict:
        """All tasks in the Project Plan with their full notes. Completed and Cancelled
        tasks are left out unless include_closed is true."""
        p = rt.require()
        return {"tasks": [t.brief(full_notes=True) for t in p.tasks
                          if include_closed or t.status not in CLOSED]}

    @tool
    @safe
    def search_activity_log(task_id: str = "", action_type: str = "",
                            recipient: str = "", days: int = 14) -> list:
        """Search Activity Log rows from the last `days` days, e.g. to count follow-ups
        already sent on the same point or to check what was done before."""
        return rt.search_log(task_id, action_type, recipient, rt.now() - timedelta(days=days))

    @tool
    @safe
    def log_activity(action_type: str, summary: str, task_id: str = "", recipient: str = "",
                     channel: str = "Email", status: str = "Recorded") -> dict:
        """Write an Activity Log row for an action no other tool logged (e.g. 'Date change',
        'Stalled recovery', 'Conflict'). Sends and sheet writes are logged automatically."""
        rt.require()
        rt.log(action_type, summary, recipient=recipient, channel=channel, status=status,
               task_ids=[task_id] if task_id else [])
        return {"logged": True}

    return [get_run_context, read_project_plan, search_activity_log, log_activity]
