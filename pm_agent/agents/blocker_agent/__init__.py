"""Blocker Agent: blockers and dependencies (section 11)."""
from pathlib import Path

from ...core.handoffs import pending_handoffs
from ..base import AgentSpec, AgentTask

SPEC = AgentSpec(
    name="blocker_agent",
    title="Blocker Agent",
    description="Works blocker reports handed over by the Reply Agent: records the block on "
                "both tasks, emails both owners with the PM in copy, flags circular blocks.",
    tools=[
        "get_run_context", "read_project_plan", "search_activity_log",
        "get_blocker_handoffs", "complete_blocker_handoff",
        "set_task_blocked", "clear_task_blocker", "append_task_note",
        "send_email", "send_chat",
    ],
    send_actions=frozenset({"Blocker email", "Blocker cleared", "Follow-up question", "Alert"}),
    tasks={
        "handle_blockers": AgentTask(
            instructions="Handle every pending blocker hand-off now, following your role.",
            has_work=lambda rt: bool(pending_handoffs(rt, "blocker_agent")),
            working_day_only=False,
        ),
    },
    prompt_file=Path(__file__).with_name("prompt.md"),
)
