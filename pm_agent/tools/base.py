"""Helpers shared by the tool modules."""
from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from ..core.runtime import Runtime

log = logging.getLogger("pm_agent")


@dataclass(frozen=True)
class ToolContext:
    """What a tool knows about the agent that is calling it."""
    rt: Optional[Runtime]          # None only when listing tool names
    agent_name: str
    send_actions: frozenset[str]   # Activity Log action types this agent may send


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def safe(fn):
    """Return results as JSON and turn exceptions into an error the model can read."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return to_json(fn(*args, **kwargs))
        except Exception as e:
            log.exception("Tool %s failed", fn.__name__)
            return to_json({"error": f"{type(e).__name__}: {e}"})
    return wrapper
