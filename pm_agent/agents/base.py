"""What an agent is, and how one is run.

An agent = a prompt file + a list of tools + the action types it may send + a set
of named tasks. Every agent gets shared_rules.md in front of its own prompt.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..config import MAILBOX_PLACEHOLDER
from ..core.runtime import Runtime
from ..tools import build_tools

log = logging.getLogger("pm_agent")

SHARED_RULES = Path(__file__).with_name("shared_rules.md")


def _always(rt: Runtime) -> bool:
    return True


@dataclass
class AgentTask:
    """One job an agent can be asked to do."""
    instructions: str
    # Cheap check run before the model is called; False means "nothing to do, skip".
    has_work: Callable[[Runtime], bool] = _always
    working_day_only: bool = True
    runs_on_broken_sheet: bool = False
    # A deterministic step that needs no model (instructions are then documentation).
    direct: Optional[Callable[[Runtime], Any]] = None


@dataclass
class AgentSpec:
    name: str
    title: str
    description: str
    tools: list[str]
    send_actions: frozenset[str]
    tasks: dict[str, AgentTask]
    prompt_file: Path
    extra: dict = field(default_factory=dict)

    def system_prompt(self, mailbox: str) -> str:
        shared = SHARED_RULES.read_text("utf-8")
        own = self.prompt_file.read_text("utf-8")
        allowed = ", ".join(sorted(self.send_actions)) or "none"
        text = (f"{shared}\n\n# Your role: {self.title}\n\n{own}\n\n"
                f"Action types you may send: {allowed}.\n")
        return text.replace(MAILBOX_PLACEHOLDER, mailbox)


@dataclass
class AgentResult:
    agent: str
    task: str
    status: str            # "done", "skipped" or "failed"
    output: str = ""


def build_agent(spec: AgentSpec, rt: Runtime):
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI

    tools = build_tools(rt, spec.name, spec.tools, spec.send_actions)
    return create_agent(model=ChatOpenAI(model=rt.cfg.model_for(spec.name)), tools=tools,
                        system_prompt=spec.system_prompt(rt.cfg.agent_mailbox), name=spec.name)


def run_agent(spec: AgentSpec, task_name: str, rt: Runtime, force: bool = False,
              note: str = "") -> AgentResult:
    """Run one task of one agent against one project sheet."""
    if task_name not in spec.tasks:
        raise KeyError(f"{spec.name} has no task '{task_name}'. Tasks: {sorted(spec.tasks)}")
    task = spec.tasks[task_name]
    p = rt.project(refresh=True)

    def skip(why: str) -> AgentResult:
        log.info("[%s] %s.%s skipped: %s", rt.sheet_id[:8], spec.name, task_name, why)
        return AgentResult(spec.name, task_name, "skipped", why)

    if p.fatal and not task.runs_on_broken_sheet:
        return skip("sheet has problems")
    if not p.fatal and task.working_day_only and not p.is_working_day(rt.today()):
        return skip("not a working day")
    if not force and not task.has_work(rt):
        return skip("nothing to do")

    if task.direct:
        out = task.direct(rt)
        log.info("[%s] %s.%s done: %s", rt.sheet_id[:8], spec.name, task_name, out)
        return AgentResult(spec.name, task_name, "done", str(out))

    msg = (f"Task: {task_name}\n{task.instructions}\n\n"
           f"Project sheet for this run: {rt.sheet_url}\n"
           f"Current time: {rt.now():%Y-%m-%d %H:%M} IST ({rt.now():%A}).")
    if note:
        msg += f"\n\nNote from the orchestrator: {note}"
    result = build_agent(spec, rt).invoke({"messages": [{"role": "user", "content": msg}]},
                                          config={"recursion_limit": 200})
    final = result["messages"][-1].content
    if isinstance(final, list):
        final = "\n".join(b.get("text", "") for b in final if isinstance(b, dict))
    log.info("[%s] %s.%s done:\n%s", rt.sheet_id[:8], spec.name, task_name, final)
    return AgentResult(spec.name, task_name, "done", final)
