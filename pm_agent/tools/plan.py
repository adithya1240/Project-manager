"""Tools that write to the Project Plan (section 1 allow-list only)."""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from ..core import plan_writes
from .base import ToolContext, safe


def build(ctx: ToolContext) -> list:
    rt = ctx.rt

    @tool
    @safe
    def record_task_update(task_id: str, note: str, author_name: str,
                           percent: Optional[int] = None, status: Optional[str] = None,
                           confirmed_lower: bool = False, received_at: Optional[str] = None,
                           channel: str = "Email", sender_email: str = "") -> dict:
        """Record an owner's update on one task: writes % Complete (0-100, optional),
        prepends the note as 'received_at - author_name: note' and sets Last Update Date
        to today. status only for a status the owner reported (In Progress, On Hold,
        Completed; Completed needs 100). A lower percent needs the owner's confirmation
        first (confirmed_lower=true), then tell the alert recipient.
        received_at: the reply's real time, e.g. '2026-10-15 11:20'."""
        return plan_writes.record_task_update(rt, task_id, note, author_name, percent, status,
                                              confirmed_lower, received_at, channel, sender_email)

    @tool
    @safe
    def append_task_note(task_id: str, note: str, author_name: str = "PM Agent") -> dict:
        """Prepend a note line to a task (never overwrites)."""
        return plan_writes.append_task_note(rt, task_id, note, author_name)

    @tool
    @safe
    def add_followup_task(task_name: str, reason: str, supports_task_id: str,
                          workstream: Optional[str] = None) -> dict:
        """Add a follow-up task row with status Task Review Pending and no owner or dates,
        then send it to the alert recipient for review."""
        return plan_writes.add_followup_task(rt, task_name, reason, supports_task_id, workstream)

    @tool
    @safe
    def set_task_blocked(task_id: str, reason: str, reported_by: str,
                         blocking_task_id: Optional[str] = None,
                         external_party: Optional[str] = None) -> dict:
        """Record a block: sets the task to Blocked and writes Blocker Details and notes
        on both tasks. Give blocking_task_id for a task in the plan, or external_party for
        anything else. Says whether to send the joint email and flags circular blocks."""
        return plan_writes.set_task_blocked(rt, task_id, reason, reported_by,
                                            blocking_task_id, external_party)

    @tool
    @safe
    def clear_task_blocker(task_id: str, note: str, reported_by: str) -> dict:
        """Record that a block is cleared and set the task back to In Progress."""
        return plan_writes.clear_task_blocker(rt, task_id, note, reported_by)

    return [record_task_update, append_task_note, add_followup_task,
            set_task_blocked, clear_task_blocker]
