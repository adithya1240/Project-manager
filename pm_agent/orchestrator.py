"""Orchestrator: which agents run, in what order, for each scheduled job.

The orchestrator is plain Python, not a model, so the run order is predictable
and costs nothing. Each step is "agent_name.task_name". A step whose agent has
nothing to do is skipped without calling the model.

To change what happens at a given time, edit PIPELINES. To change how an agent
does its part, edit that agent's folder under agents/.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from typing import Optional

from .agents import AGENTS, AgentResult, run_agent
from .config import (DAILY_REQUEST_AT, END_OF_DAY_AT, FIRST_PING_AFTER, IST, POLL_EVERY_MINUTES,
                     POLL_HOURS, PRE_DELIVERY_CHAT_AFTER, SECOND_PING_AT, Config)
from .core.runtime import Runtime
from .core.workspace import Workspace

log = logging.getLogger("pm_agent")

# Replies and blockers are always handled first, so a fresh reply stops a ping
# and a reported block is acted on before anything else is sent.
FIRST = ["reply_agent.process_replies", "blocker_agent.handle_blockers"]

PIPELINES: dict[str, list[str]] = {
    "morning": ["data_quality_agent.sheet_broken", *FIRST,
                "reminder_agent.assign_and_request",
                "data_quality_agent.report_issues",
                "monitoring_agent.daily_checks"],
    "first_ping": [*FIRST, "reminder_agent.first_ping"],
    "pre_delivery_chat": [*FIRST, "monitoring_agent.pre_delivery_chat"],
    "second_ping": [*FIRST, "reminder_agent.second_ping"],
    "end_of_day": [*FIRST, "reminder_agent.end_of_day"],
    "poll": FIRST,
}


def _at(t, delta=None):
    dt = datetime.combine(date.today(), t)
    return (dt + delta).time() if delta else t


# job -> (days, time); None time means the polling trigger.
SCHEDULE = {
    "morning": ("*", _at(DAILY_REQUEST_AT)),          # every day: assignment emails go out on any day
    "first_ping": ("mon-fri", _at(DAILY_REQUEST_AT, FIRST_PING_AFTER)),
    "pre_delivery_chat": ("mon-fri", _at(DAILY_REQUEST_AT, PRE_DELIVERY_CHAT_AFTER)),
    "second_ping": ("mon-fri", SECOND_PING_AT),
    "end_of_day": ("mon-fri", END_OF_DAY_AT),
    "poll": ("*", None),
}


def validate() -> None:
    """Fail fast if a pipeline names an agent or task that does not exist."""
    for job, steps in PIPELINES.items():
        for step in steps:
            agent, _, task = step.partition(".")
            if agent not in AGENTS or task not in AGENTS[agent].tasks:
                raise KeyError(f"Pipeline '{job}' has unknown step '{step}'")


def run_job(cfg: Config, ws: Workspace, sheet_url: str, job: str,
            now: Optional[datetime] = None) -> list[AgentResult]:
    """Run every step of one job for one project sheet."""
    rt = Runtime(cfg, ws, sheet_url, now=now)
    results = []
    for step in PIPELINES[job]:
        agent, _, task = step.partition(".")
        try:
            results.append(run_agent(AGENTS[agent], task, rt))
        except Exception as e:  # one agent failing must not stop the others
            log.exception("[%s] %s failed", rt.sheet_id[:8], step)
            results.append(AgentResult(agent, task, "failed", str(e)))
    return results


def serve(cfg: Config, sheets: list[str]) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    validate()
    ws = Workspace(cfg)
    lock = threading.Lock()  # jobs run one at a time; Google clients are not thread-safe

    def make(job: str):
        def fn():
            with lock:
                for url in sheets:
                    try:
                        run_job(cfg, ws, url, job)
                    except Exception:
                        log.exception("Job %s failed for %s", job, url)
        return fn

    sched = BlockingScheduler(timezone=IST)
    for job, (days, t) in SCHEDULE.items():
        if t is None:
            trigger = CronTrigger(day_of_week=days, hour=POLL_HOURS,
                                  minute=f"*/{POLL_EVERY_MINUTES}", timezone=IST)
        else:
            trigger = CronTrigger(day_of_week=days, hour=t.hour, minute=t.minute, timezone=IST)
        sched.add_job(make(job), trigger, id=job, max_instances=1, coalesce=True,
                      misfire_grace_time=3600)
    log.info("Serving %d project(s); jobs: %s", len(sheets), ", ".join(SCHEDULE))
    sched.start()
