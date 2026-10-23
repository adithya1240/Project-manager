"""Settings shared by every agent: environment config, schedule and business rules.

Change a timing or threshold here and every agent and tool picks it up.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
MAILBOX_PLACEHOLDER = "[AGENT_MAILBOX_EMAIL]"

# --- Schedule (IST) -------------------------------------------------------
DAILY_REQUEST_AT = dtime(10, 0)
FIRST_PING_AFTER = timedelta(minutes=30)
SECOND_PING_AT = dtime(16, 0)
PRE_DELIVERY_CHAT_AFTER = timedelta(hours=2)
END_OF_DAY_AT = dtime(18, 30)
POLL_EVERY_MINUTES = 10
POLL_HOURS = "8-20"

# --- Rules ----------------------------------------------------------------
STALLED_AFTER_WORKING_DAYS = 2
LONG_STUCK_WORKING_DAYS = 7
PRE_DELIVERY_WINDOW_DAYS = 15
REPLY_LOOKBACK_DAYS = 3
MAX_FOLLOW_UPS_PER_POINT = 2

STATUSES = ("Not Started", "In Progress", "Blocked", "On Hold",
            "Task Review Pending", "Completed", "Cancelled")
CLOSED = {"Completed", "Cancelled"}
OWNER_REPORTABLE = {"In Progress", "Blocked", "On Hold", "Completed"}
SENT_OK = {"Sent", "Delivered"}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.spaces",
]


@dataclass
class Config:
    agent_mailbox: str
    service_account_file: str
    model: str
    state_dir: Path

    def model_for(self, agent_name: str) -> str:
        """Per-agent model override, e.g. PMA_MODEL_REMINDER_AGENT=gpt-5-mini."""
        return os.environ.get(f"PMA_MODEL_{agent_name.upper()}", self.model)

    @classmethod
    def from_env(cls) -> "Config":
        mailbox = os.environ.get("AGENT_MAILBOX_EMAIL", "").strip()
        if not mailbox or mailbox == MAILBOX_PLACEHOLDER or "@" not in mailbox:
            sys.exit("Set AGENT_MAILBOX_EMAIL to the dedicated agent mailbox before running.")
        key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        if not key or not Path(key).is_file():
            sys.exit("Set GOOGLE_SERVICE_ACCOUNT_FILE to the service-account JSON key.")
        return cls(agent_mailbox=mailbox, service_account_file=key,
                   model=os.environ.get("OPENAI_MODEL", "gpt-5"),
                   state_dir=Path(os.environ.get("PMA_STATE_DIR", PROJECT_DIR / ".pm_agent_state")))
