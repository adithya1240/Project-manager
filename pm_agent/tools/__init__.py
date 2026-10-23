"""Tool library. Agents pick the tools they need by name.

To add a tool: write it in one of these modules (or a new one listed in
MODULES), then add its name to the `tools` list of the agents that need it.
"""
from __future__ import annotations

from typing import Optional

from ..core.runtime import Runtime
from . import context, handoff, messaging, plan, replies, reports
from .base import ToolContext

MODULES = (context, messaging, replies, plan, handoff, reports)


def build_tools(rt: Optional[Runtime], agent_name: str, names: list[str],
                send_actions: frozenset[str]) -> list:
    ctx = ToolContext(rt=rt, agent_name=agent_name, send_actions=send_actions)
    available = {t.name: t for m in MODULES for t in m.build(ctx)}
    missing = [n for n in names if n not in available]
    if missing:
        raise KeyError(f"{agent_name} asks for unknown tool(s): {missing}")
    return [available[n] for n in names]


def available_tool_names() -> list[str]:
    ctx = ToolContext(rt=None, agent_name="", send_actions=frozenset())
    return [t.name for m in MODULES for t in m.build(ctx)]
