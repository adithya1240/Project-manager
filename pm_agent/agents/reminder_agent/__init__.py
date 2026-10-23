"""Reminder Agent: assignment emails, daily requests and pings (sections 5, 6, 9)."""
from pathlib import Path

from ...core import planning
from ..base import AgentSpec, AgentTask


def _awaiting(pings: int):
    def check(rt) -> bool:
        return any(o["pings_sent_today"] == pings and not o["on_leave_today"]
                   for o in planning.owners_awaiting_reply(rt))
    return check


SPEC = AgentSpec(
    name="reminder_agent",
    title="Reminder Agent",
    description="Sends assignment emails, the daily 10 AM update requests and the "
                "no-response chat pings; logs 'No response' at end of day.",
    tools=[
        "get_run_context",
        "get_assignment_plan", "get_daily_request_plan", "get_owners_awaiting_reply",
        "send_email", "send_chat",
    ],
    send_actions=frozenset({"Assignment", "Daily request", "Reminder ping"}),
    tasks={
        "assign_and_request": AgentTask(
            instructions="Send today's assignment emails (any day), then, if today is a "
                         "working day, the daily update requests.",
            has_work=lambda rt: bool(planning.assignment_plan(rt)
                                     or planning.daily_request_plan(rt)["daily_requests"]),
            working_day_only=False,
        ),
        "first_ping": AgentTask(
            instructions="Send the first no-response chat ping to each owner who has not "
                         "replied and has had no ping yet today.",
            has_work=_awaiting(0),
        ),
        "second_ping": AgentTask(
            instructions="Send the afternoon chat ping to each owner who still has not "
                         "replied and has had exactly one ping today.",
            has_work=_awaiting(1),
        ),
        "end_of_day": AgentTask(
            instructions="Log 'No response' against each task of every owner who never "
                         "replied today (deterministic, no model).",
            direct=planning.record_no_responses,
        ),
    },
    prompt_file=Path(__file__).with_name("prompt.md"),
)
