"""Reply Agent: reads owner replies and records their updates (sections 7 and 8)."""
from pathlib import Path

from ...core.replies import fetch_new_replies
from ..base import AgentSpec, AgentTask

SPEC = AgentSpec(
    name="reply_agent",
    title="Reply Agent",
    description="Reads owner replies on email and chat, records % complete and notes, "
                "follows up on unclear points, hands blocker reports to the Blocker Agent.",
    tools=[
        "get_run_context", "read_project_plan", "search_activity_log",
        "fetch_new_replies", "mark_reply_processed",
        "record_task_update", "append_task_note", "add_followup_task",
        "hand_off_to_blocker_agent",
        "send_email", "send_chat",
    ],
    send_actions=frozenset({"Acknowledgement", "Follow-up question", "Alert"}),
    tasks={
        "process_replies": AgentTask(
            instructions="Process every new reply now, following your role.",
            has_work=lambda rt: bool(fetch_new_replies(rt)),
            working_day_only=False,
        ),
    },
    prompt_file=Path(__file__).with_name("prompt.md"),
)
