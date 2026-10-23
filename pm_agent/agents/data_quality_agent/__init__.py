"""Data Quality Agent: problems in the plan itself (section 14)."""
from pathlib import Path

from ...core import planning
from ..base import AgentSpec, AgentTask


def _sheet_broken(rt) -> bool:
    p = rt.project()
    return bool(p.fatal) and not rt.rows_today(p, "Data issue alert")


def _issues_to_report(rt) -> bool:
    r = planning.data_issue_report(rt)
    return bool((r["issues"] and not r["alert_already_sent_today"])
                or (r["date_changes_today"] and not r["date_changes_already_logged"]))


SPEC = AgentSpec(
    name="data_quality_agent",
    title="Data Quality Agent",
    description="Tells the PM when the sheet cannot be used, and once a day about plan "
                "problems (owners, dates, leave clashes, conflicts); logs plan date changes.",
    tools=["get_run_context", "get_data_issues", "log_activity", "send_email", "send_chat"],
    send_actions=frozenset({"Data issue alert"}),
    tasks={
        "sheet_broken": AgentTask(
            instructions="The sheet has problems that stop all work. Tell the Project Manager.",
            has_work=_sheet_broken,
            working_day_only=False,
            runs_on_broken_sheet=True,
        ),
        "report_issues": AgentTask(
            instructions="Report today's plan problems and log any plan date changes.",
            has_work=_issues_to_report,
        ),
    },
    prompt_file=Path(__file__).with_name("prompt.md"),
)
