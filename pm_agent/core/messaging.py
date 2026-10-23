"""Sending email and chat: guard, retry once, log (sections 13 and 14)."""
from __future__ import annotations

from typing import Optional

from .guards import check_recipients, check_send
from .runtime import Runtime


def send_email(rt: Runtime, to: list[str], subject: str, body: str, action: str,
               task_ids: list[str], cc: list[str], reply_to_id: Optional[str],
               summary: str) -> dict:
    p = rt.project(refresh=True)
    # A broken sheet blocks everything except telling the PM about it.
    if p.fatal and not (action == "Data issue alert" and p.team):
        return {"error": "Sheet problems, act on nothing: " + "; ".join(p.fatal)}
    to = [a.strip().lower() for a in to if a.strip()]
    cc = [a.strip().lower() for a in cc if a.strip()]
    if not to:
        return {"error": "No recipient."}
    err = check_recipients(p, to + cc) or check_send(rt, p, action, "Email", to, task_ids)
    if err:
        return {"error": err, "sent": False}
    ref = None
    if reply_to_id:
        if not reply_to_id.startswith("gmail:"):
            return {"error": "reply_to_id must be a gmail: reply id; answer chat with send_chat."}
        ref = rt.ws.email_reply_ref(reply_to_id[6:])
        if not subject:
            subject = ref["subject"] if ref["subject"].lower().startswith("re:") \
                else f"Re: {ref['subject']}"
    try:
        _, thread = rt.ws.send_email(to, cc, subject, body, ref)
    except Exception:
        try:
            _, thread = rt.ws.send_email(to, cc, subject, body, ref)
        except Exception as e:
            rt.log(action, f"FAILED after retry: {subject} ({e})",
                   recipient=", ".join(to), status="Failed", task_ids=task_ids)
            return {"sent": False, "error": f"Send failed after one retry: {e}. "
                    "Tell the Project Manager by chat and move on."}
    if action == "Pre-delivery list":
        rt.state.data["pre_delivery"][rt.today().isoformat()] = thread
        rt.state.save()
    rt.log(action, summary or subject, recipient=", ".join(to + cc),
           status="Sent", task_ids=task_ids)
    return {"sent": True, "thread_id": thread}


def send_chat(rt: Runtime, to: str, text: str, action: str, task_ids: list[str],
              summary: str) -> dict:
    p = rt.require()
    to = to.strip().lower()
    err = check_recipients(p, [to]) or check_send(rt, p, action, "Chat", [to], task_ids)
    if err:
        return {"error": err, "sent": False}
    try:
        res = rt.ws.send_chat(to, text)
    except Exception:
        try:
            res = rt.ws.send_chat(to, text)
        except Exception as e:
            rt.log(action, f"FAILED after retry: {summary or text[:80]} ({e})",
                   recipient=to, channel="Chat", status="Failed", task_ids=task_ids)
            return {"sent": False, "error": f"Chat failed after one retry: {e}. "
                    "Tell the Project Manager by email and move on."}
    if res.get("name") and res["name"] != "dry-run":
        rt.state.data["chat_sent"][res["name"]] = rt.now().isoformat()
        if res.get("sender", {}).get("name"):
            rt.state.data["chat_self"] = res["sender"]["name"]
        rt.state.save()
    rt.log(action, summary or text[:120], recipient=to, channel="Chat",
           status="Sent", task_ids=task_ids)
    return {"sent": True}
