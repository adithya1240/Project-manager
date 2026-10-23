"""Send guards: checked against the Activity Log before anything goes out.

These are the rules from sections 6, 9, 10, 12 and 13 that must hold even if a
model gets it wrong: no duplicates on the same day, ping timing, leave, and
only Team-tab recipients. Each returns None when the send is allowed, or the
reason it is refused.
"""
from __future__ import annotations

from typing import Optional

from ..config import DAILY_REQUEST_AT, FIRST_PING_AFTER, SECOND_PING_AT, SENT_OK
from .runtime import Runtime
from .sheet import Project, split_emails


def check_recipients(p: Project, addrs: list[str]) -> Optional[str]:
    allowed = p.team_emails()
    bad = [a for a in addrs if a.lower() not in allowed]
    return f"Not in the Team tab, cannot send: {bad}" if bad else None


def check_send(rt: Runtime, p: Project, action: str, channel: str,
               recipients: list[str], task_ids: list[str]) -> Optional[str]:
    now, today = rt.now(), rt.today()
    rows = rt.rows_today(p, action)
    to = recipients[0].lower() if recipients else ""
    owner = p.name_of_email(to) or ""

    if action == "Assignment":
        if not task_ids:
            return "Assignment sends need task_ids."
        done = {r["task_id"] for r in p.log_rows
                if r["action"] == "Assignment" and r["status"] in SENT_OK}
        dup = [t for t in task_ids if t in done]
        if dup:
            return f"Assignment already sent for {dup}. Send again without them."

    elif action == "Daily request":
        if not p.is_working_day(today):
            return "Today is not a working day; no daily requests."
        if now.time() < DAILY_REQUEST_AT:
            return f"Daily requests go out from {DAILY_REQUEST_AT:%H:%M} IST."
        if any(to in split_emails(r["recipient"]) for r in rows):
            return f"Daily request already sent to {to} today."
        if owner and p.leave_on(owner, today):
            return f"{owner} is on leave today; do not send."

    elif action == "Reminder ping":
        if channel != "Chat":
            return "Reminder pings go on Google Chat."
        if not p.is_working_day(today):
            return "Today is not a working day; no pings."
        if owner and p.leave_on(owner, today):
            return f"{owner} is on leave today; do not ping."
        reqs = [r["ts"] for r in rt.rows_today(p, "Daily request")
                if to in split_emails(r["recipient"])]
        if not reqs:
            return f"No daily request went to {to} today, so no ping."
        if rt.replied_since(p, to, min(reqs)):
            return f"{to} already replied today; pings stop."
        sent = {r["ts"] for r in rows if to in split_emails(r["recipient"])}
        if len(sent) >= 2:
            return f"Two pings already sent to {to} today."
        if not sent and now < min(reqs) + FIRST_PING_AFTER:
            return "First ping is allowed 30 minutes after the daily request."
        if len(sent) == 1 and now.time() < SECOND_PING_AT:
            return f"Second ping is allowed from {SECOND_PING_AT:%H:%M} IST."

    elif action in ("Stalled alert", "Escalation"):
        if not p.is_working_day(today):
            return "Today is not a working day."
        dup = [t for t in task_ids if any(r["task_id"] == t for r in rows)]
        if dup:
            return f"{action} already sent today for {dup}. Send again without them."

    elif action == "Pre-delivery list":
        from .planning import pre_delivery_status  # local import avoids a cycle
        if any(r["channel"] == channel for r in rows):
            return f"Pre-delivery list already sent by {channel} today."
        st = pre_delivery_status(rt, p)
        if not st["in_window"]:
            return "Today is not inside the pre-delivery window."
        if channel == "Chat" and not st["chat_due"]:
            return "Chat step not due: " + st["chat_reason"]

    elif action == "Data issue alert":
        if any(to in split_emails(r["recipient"]) for r in rows):
            return "Data issue alert already sent today; use an 'Alert' for anything new."
    return None
