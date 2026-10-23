"""Command line: run the schedule, one job, or one agent on its own."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from typing import Any, Optional

from .config import IST, Config


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


def cmd_agents() -> None:
    """Print every agent, its tasks, tools and send rights, and the pipelines."""
    from .agents import AGENTS
    from .orchestrator import PIPELINES, SCHEDULE, validate
    from .tools import available_tool_names

    validate()
    known = set(available_tool_names())
    for spec in AGENTS.values():
        bad = [t for t in spec.tools if t not in known]
        print(f"\n{spec.title} ({spec.name})\n  {spec.description}")
        print(f"  prompt : {spec.prompt_file.relative_to(spec.prompt_file.parents[2])}")
        print(f"  tasks  : {', '.join(spec.tasks)}")
        print(f"  tools  : {', '.join(spec.tools)}" + (f"  UNKNOWN: {bad}" if bad else ""))
        print(f"  sends  : {', '.join(sorted(spec.send_actions))}")
    print("\nJobs:")
    for job, steps in PIPELINES.items():
        days, t = SCHEDULE[job]
        when = f"{t:%H:%M} ({days})" if t else f"every few minutes ({days})"
        print(f"  {job:<18} {when:<20} {' -> '.join(steps)}")


def cmd_check(cfg: Config, sheet: str, now: Optional[datetime]) -> None:
    """Validate the sheet and print what each agent would see. Sends nothing."""
    from .core import planning
    from .core.handoffs import pending_handoffs
    from .core.runtime import Runtime
    from .core.workspace import Workspace

    rt = Runtime(cfg, Workspace(cfg, dry_run=True), sheet, now=now)
    ctx = planning.run_context(rt)
    print(_pretty(ctx))
    if ctx.get("fatal_sheet_problems"):
        return
    for title, fn in (
            ("reminder_agent: assignments", planning.assignment_plan),
            ("reminder_agent: daily requests", planning.daily_request_plan),
            ("reminder_agent: awaiting reply", planning.owners_awaiting_reply),
            ("blocker_agent: pending hand-offs", lambda r: pending_handoffs(r, "blocker_agent")),
            ("data_quality_agent: issues", planning.data_issue_report),
            ("monitoring_agent: stalled", planning.find_stalled),
            ("monitoring_agent: long stuck", planning.find_long_stuck),
            ("monitoring_agent: pre-delivery", planning.pre_delivery_status)):
        print(f"\n=== {title} ===\n{_pretty(fn(rt))}")


def main(argv: Optional[list[str]] = None) -> None:
    from .agents import AGENTS
    from .orchestrator import PIPELINES

    ap = argparse.ArgumentParser(prog="pm_agent", description="Project Management Agent team (v1)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("agents", help="list agents, their tools and the job pipelines")

    def add_common(sp, many=False, when=True, dry=True):
        sp.add_argument("--sheet", action="append" if many else None, required=True,
                        help="project Google Sheet link" + (" (repeatable)" if many else ""))
        if when:
            sp.add_argument("--now", help="pretend IST time, e.g. 2026-10-15T10:00")
        if dry:
            sp.add_argument("--dry-run", action="store_true",
                            help="print sends and sheet writes instead of doing them")

    add_common(sub.add_parser("check", help="validate a sheet, print each agent's view"),
               dry=False)
    sp = sub.add_parser("run", help="run one scheduled job now (all its agents)")
    sp.add_argument("job", choices=sorted(PIPELINES))
    add_common(sp)
    sp = sub.add_parser("agent", help="run ONE agent on its own")
    sp.add_argument("name", choices=sorted(AGENTS))
    sp.add_argument("--task", help="task to run (default: the agent's first task)")
    sp.add_argument("--force", action="store_true", help="run even if it reports nothing to do")
    add_common(sp)
    add_common(sub.add_parser("serve", help="run the IST schedule"), many=True,
               when=False, dry=False)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "agents":
        cmd_agents()
        return

    cfg = Config.from_env()
    now = datetime.fromisoformat(args.now).replace(tzinfo=IST) if getattr(args, "now", None) else None

    if args.cmd == "serve":
        from .orchestrator import serve
        serve(cfg, args.sheet)
    elif args.cmd == "check":
        cmd_check(cfg, args.sheet, now)
    else:
        from .agents import run_agent
        from .core.runtime import Runtime
        from .core.workspace import Workspace
        from .orchestrator import run_job

        ws = Workspace(cfg, dry_run=args.dry_run)
        if args.cmd == "run":
            results = run_job(cfg, ws, args.sheet, args.job, now=now)
        else:
            spec = AGENTS[args.name]
            task = args.task or next(iter(spec.tasks))
            results = [run_agent(spec, task, Runtime(cfg, ws, args.sheet, now=now),
                                 force=args.force)]
        for r in results:
            print(f"\n--- {r.agent}.{r.task}: {r.status} ---\n{r.output}")
