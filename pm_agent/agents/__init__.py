"""Agent registry. To add an agent, create a folder like the others and list its SPEC here."""
from .base import AgentResult, AgentSpec, AgentTask, run_agent
from .blocker_agent import SPEC as BLOCKER_AGENT
from .data_quality_agent import SPEC as DATA_QUALITY_AGENT
from .monitoring_agent import SPEC as MONITORING_AGENT
from .reminder_agent import SPEC as REMINDER_AGENT
from .reply_agent import SPEC as REPLY_AGENT

AGENTS: dict[str, AgentSpec] = {s.name: s for s in (
    REPLY_AGENT, BLOCKER_AGENT, REMINDER_AGENT, MONITORING_AGENT, DATA_QUALITY_AGENT)}

__all__ = ["AGENTS", "AgentResult", "AgentSpec", "AgentTask", "run_agent"]
