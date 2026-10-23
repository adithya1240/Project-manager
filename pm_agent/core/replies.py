"""Reading owner replies from the agent mailbox and Google Chat DMs."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..config import IST, REPLY_LOOKBACK_DAYS
from .runtime import Runtime
from .workspace import parse_rfc3339

log = logging.getLogger("pm_agent")

REPLY_KINDS = {"reply": "Reply received", "auto_reply": "Auto-reply",
               "bounce": "Bounce", "not_for_this_project": None}


def fetch_new_replies(rt: Runtime) -> list[dict]:
    p = rt.project(refresh=True)
    out: list[dict] = [m for m in rt.ws.unprocessed_emails(rt.label, REPLY_LOOKBACK_DAYS)
                       if m["reply_id"] not in rt.dry_done]

    if not rt.state.data["chat_since"]:
        rt.state.data["chat_since"] = rt.now().isoformat()
        rt.state.save()
    since = max(datetime.fromisoformat(rt.state.data["chat_since"]),
                rt.now() - timedelta(days=REPLY_LOOKBACK_DAYS))
    mine = set(rt.state.data["chat_sent"]) | set(rt.state.data["chat_done"])
    me = rt.state.data.get("chat_self")
    for person in p.team:
        email = person["email"].lower()
        if not email or email == rt.ws.mailbox:
            continue
        try:
            msgs = rt.ws.chat_messages_since(email, since)
        except Exception as e:
            log.warning("Chat read failed for %s: %s", email, e)
            continue
        for m in msgs:
            rid = f"chat:{m['name']}"
            sender = m.get("sender", {})
            if (m["name"] in mine or rid in rt.dry_done or sender.get("type") == "BOT"
                    or (me and sender.get("name") == me)):
                continue
            out.append({
                "reply_id": rid, "channel": "Chat", "sender_email": email,
                "sender_display_name": person["name"],
                "received_at": parse_rfc3339(m["createTime"]).astimezone(IST),
                "subject": "", "text": (m.get("text") or "")[:4000],
                "is_auto_reply": False, "is_bounce": False,
            })
    for m in out:
        m["sender_team_name"] = p.name_of_email(m["sender_email"])
        m["sender_in_team"] = m["sender_team_name"] is not None
        m["received_at"] = m["received_at"].strftime("%Y-%m-%d %H:%M IST")
    return sorted(out, key=lambda m: m["received_at"])


def mark_reply_processed(rt: Runtime, reply_id: str, sender_email: str, kind: str,
                         summary: str, task_ids: list[str]) -> dict:
    if kind not in REPLY_KINDS:
        return {"error": f"kind must be one of {sorted(REPLY_KINDS)}"}
    if rt.ws.dry_run:
        rt.dry_done.add(reply_id)
    elif reply_id.startswith("gmail:"):
        rt.ws.mark_email_processed(reply_id[6:], rt.label)
    elif reply_id.startswith("chat:"):
        rt.state.data["chat_done"][reply_id[5:]] = rt.now().isoformat()
        rt.state.save()
    else:
        return {"error": f"Unknown reply id {reply_id}"}
    action = REPLY_KINDS[kind]
    if action:
        rt.log(action, summary, recipient=sender_email.lower(),
               channel="Chat" if reply_id.startswith("chat:") else "Email", task_ids=task_ids)
    return {"marked": True}
