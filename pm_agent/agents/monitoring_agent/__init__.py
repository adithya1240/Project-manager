"""Monitoring Agent: stalled, long-stuck and pre-delivery escalation (sections 10, 12)."""
from pathlib import Path

from ...core import planning
from ..base import AgentSpec, AgentTask


def _daily_checks_needed(rt) -> bool:
    stalled = planning.find_stalled(rt)
    return bool(stalled["stalled"] or stalled["recovered"]
                or planning.find_long_stuck(rt)["tasks"]
                or planning.pre_delivery_status(rt)["email_due"])


SPEC = AgentSpec(
    name="monitoring_agent",
    title="Monitoring Agent",
    description="Alerts on stalled tasks, escalates long-stuck tasks to the Program Manager "
                "Head, and sends the pre-delivery blockers list in the last 15 days.",
    tools=[
        "get_run_context", "read_project_plan",
        "find_stalled_tasks", "find_long_stuck_tasks", "get_pre_delivery_status",
        "append_task_note", "log_activity",
        "send_email", "send_chat",
    ],
    send_actions=frozenset({"Stalled alert", "Escalation", "Pre-delivery list"}),
    tasks={
        "daily_checks": AgentTask(
            instructions="Run today's checks in this order: stalled tasks, long-stuck tasks, "
                         "then the pre-delivery email if it is due.",
            has_work=_daily_checks_needed,
        ),
        "pre_delivery_chat": AgentTask(
            instructions="If the pre-delivery email has had no reply for two hours, send the "
                         "refreshed list by Google Chat. Otherwise do nothing.",
            has_work=lambda rt: planning.pre_delivery_status(rt)["chat_due"],
        ),
    },
    prompt_file=Path(__file__).with_name("prompt.md"),
)
