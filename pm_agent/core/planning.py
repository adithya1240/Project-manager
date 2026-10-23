"""Deterministic views of the plan: who to remind, what is stalled, stuck or wrong.

The agents act on these results; the calendar, leave and eligibility rules are
computed here so the models never have to guess them.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from ..config import (CLOSED, END_OF_DAY_AT, LONG_STUCK_WORKING_DAYS, PRE_DELIVERY_CHAT_AFTER,
                      PRE_DELIVERY_WINDOW_DAYS, SENT_OK, STALLED_AFTER_WORKING_DAYS)
from .runtime import Runtime
from .sheet import Project, iso, split_emails


# --- context --------------------------------------------------------------

def run_context(rt: Runtime) -> dict:
    p = rt.project(refresh=True)
    today = rt.today()
    now = rt.now().strftime("%Y-%m-%d %H:%M (%A)")
    if p.fatal:
        pm = p.role_person("pm")
        return {"now_ist": now, "fatal_sheet_problems": p.fatal,
                "project_manager_email": p.email_of(pm) if pm else None,
                "instruction": "Do not act on this data."}
    return {
        "now_ist": now,
        "sheet": rt.sheet_url,
        "project": p.info,
        "is_working_day": p.is_working_day(today),
        "holiday_today": p.holidays.get(today),
        "on_leave_today": sorted({n for n, s, e, _ in p.leave if s <= today <= e}),
        "alert_recipient": rt.alert_recipient(p),
        "team": p.team,
    }


# --- daily snapshot (feeds stalled detection and date-change detection) ----

def take_snapshot(rt: Runtime, p: Project) -> None:
    """Store today's pct/status/dates once per working day and record date changes."""
    today = rt.today()
    snaps = rt.state.data["snapshots"]
    key = today.isoformat()
    if not p.is_working_day(today) or key in snaps:
        return
    prev_key = max((d for d in snaps if d < key), default=None)
    prev = snaps.get(prev_key, {}) if prev_key else {}
    snaps[key], changes = {}, []
    for t in p.tasks:
        snap = {"pct": t.pct, "status": t.status, "start": iso(t.start), "due": iso(t.due)}
        snaps[key][t.task_id] = snap
        old = prev.get(t.task_id)
        if old:
            for f in ("start", "due"):
                if old[f] != snap[f]:
                    changes.append({"task_id": t.task_id, "field": f,
                                    "was": old[f], "now": snap[f]})
    rt.state.data["date_changes"][key] = changes
    rt.state.prune(today)
    rt.state.save()


# --- Reminder Agent views (sections 5, 6, 9) --------------------------------

def assignment_plan(rt: Runtime) -> list[dict]:
    """Owners to send an assignment email to today (any day of the week)."""
    p = rt.require()
    today = rt.today()
    assigned = {r["task_id"] for r in p.log_rows
                if r["action"] == "Assignment" and r["status"] in SENT_OK}
    out: dict[str, list] = defaultdict(list)
    for t in p.tasks:
        if t.status in CLOSED or t.start != today or t.task_id in assigned or p.owner_problem(t):
            continue
        out[p.email_of(t.owner)].append(t.brief())
    return [{"owner_email": e, "owner": p.name_of_email(e), "tasks": ts} for e, ts in out.items()]


def daily_request_plan(rt: Runtime) -> dict:
    """Combined daily requests per owner, overdue first (working days only)."""
    p = rt.require()
    today = rt.today()
    if not p.is_working_day(today):
        return {"is_working_day": False, "daily_requests": []}
    requested = {e for r in rt.rows_today(p, "Daily request") for e in split_emails(r["recipient"])}
    requests: dict[str, list] = defaultdict(list)
    on_leave, already = [], []
    for t in p.tasks:
        if (t.status in CLOSED or t.status in ("On Hold", "Task Review Pending")
                or p.owner_problem(t) or not t.start or t.start >= today):
            continue
        overdue = bool(t.due and t.due < today)
        if t.status not in ("In Progress", "Blocked") and not overdue:
            continue
        email = p.email_of(t.owner)
        if p.leave_on(t.owner, today):
            on_leave.append(t.task_id)
        elif email.lower() in requested:
            already.append(t.task_id)
        else:
            requests[email].append(t.brief() | {
                "overdue": overdue,
                "working_days_left": p.working_days_between(today, t.due) if t.due else None})
    for items in requests.values():
        items.sort(key=lambda x: (not x["overdue"], x["due"] or "9999"))
    return {"is_working_day": True,
            "daily_requests": [{"owner_email": e, "owner": p.name_of_email(e), "tasks": ts}
                               for e, ts in requests.items()],
            "skipped_owner_on_leave": on_leave, "already_requested_today": already}


def owners_awaiting_reply(rt: Runtime, p: Optional[Project] = None) -> list[dict]:
    p = p or rt.require()
    today_reqs: dict[str, list[dict]] = defaultdict(list)
    for r in rt.rows_today(p, "Daily request"):
        for e in split_emails(r["recipient"]):
            today_reqs[e].append(r)
    pings = rt.rows_today(p, "Reminder ping")
    out = []
    for email, rows in today_reqs.items():
        first = min(r["ts"] for r in rows)
        if rt.replied_since(p, email, first):
            continue
        name = p.name_of_email(email)
        out.append({"owner": name, "owner_email": email,
                    "request_sent_at": first.strftime("%H:%M"),
                    "task_ids": sorted({r["task_id"] for r in rows if r["task_id"]}),
                    "pings_sent_today": len({r["ts"] for r in pings
                                             if email in split_emails(r["recipient"])}),
                    "on_leave_today": bool(name and p.leave_on(name, rt.today()))})
    return out


def record_no_responses(rt: Runtime) -> dict:
    """End of day: log 'No response' for each task of owners who never replied."""
    p = rt.require()
    if rt.now().time() < END_OF_DAY_AT:
        return {"error": f"Only at end of day ({END_OF_DAY_AT:%H:%M} IST)."}
    done = {r["task_id"] for r in rt.rows_today(p, "No response", ok_only=False)}
    recorded = []
    for o in owners_awaiting_reply(rt, p):
        ids = [t for t in o["task_ids"] if t not in done]
        if ids:
            rt.log("No response", f"No response today from {o['owner']}",
                   recipient=o["owner_email"], task_ids=ids)
            recorded.append({"owner": o["owner"], "task_ids": ids})
    return {"recorded": recorded}


# --- Data Quality Agent view (section 14) -----------------------------------

def data_issue_report(rt: Runtime) -> dict:
    p = rt.require()
    today = rt.today()
    issues = list(p.issues)
    for t in p.tasks:
        if t.status in CLOSED:
            continue
        problem = p.owner_problem(t)
        if problem:
            issues.append(problem)
            continue
        leave = p.leave_on(t.owner, t.due) if t.due and t.due >= today else None
        if leave:
            issues.append(f"{t.task_id} is due {iso(t.due)} while {t.owner} is on leave "
                          f"{iso(leave[0])} to {iso(leave[1])}")
    take_snapshot(rt, p)
    pm = rt.alert_recipient(p)
    return {"issues": sorted(set(issues)),
            "date_changes_today": rt.state.data["date_changes"].get(today.isoformat(), []),
            "date_changes_already_logged": any(
                r["action"] == "Date change" for r in rt.rows_today(p, ok_only=False)),
            "alert_already_sent_today": any(
                pm["email"] and pm["email"].lower() in split_emails(r["recipient"])
                for r in rt.rows_today(p, "Data issue alert")),
            "alert_recipient": pm}


# --- Monitoring Agent views (sections 10, 12) -------------------------------

def find_stalled(rt: Runtime) -> dict:
    p = rt.require()
    today = rt.today()
    if not p.is_working_day(today):
        return {"stalled": [], "recovered": [], "note": "Not a working day."}
    take_snapshot(rt, p)
    snaps = rt.state.data["snapshots"]
    prev_days = sorted((d for d in snaps if d < today.isoformat()), reverse=True)
    stalled, now_ids = [], set()
    for t in p.tasks:
        if t.status != "In Progress" or t.pct is None:
            continue
        since = None
        for d in prev_days:
            s = snaps[d].get(t.task_id)
            if not s or s["status"] != "In Progress" or s["pct"] is None or s["pct"] < t.pct:
                break
            since = date.fromisoformat(d)
        days = p.working_days_between(since, today) if since else 0
        if days >= STALLED_AFTER_WORKING_DAYS:
            now_ids.add(t.task_id)
            stalled.append(t.brief(full_notes=True) | {
                "working_days_not_moved": days,
                "working_days_left": p.working_days_between(today, t.due) if t.due else None,
                "owner_on_leave_today": bool(p.leave_on(t.owner, today)),
                "alert_recipient": rt.alert_recipient(p, t.owner),
            })
    # Recovered = stalled on the previous working day, not stalled now.
    by_day = rt.state.data["stalled_by_day"]
    prev = max((d for d in by_day if d < today.isoformat()), default=None)
    recovered = []
    for tid in set(by_day.get(prev, [])) - now_ids if prev else ():
        t = p.task(tid)
        if t and t.status == "In Progress":
            recovered.append(t.brief())
    by_day[today.isoformat()] = sorted(now_ids)
    rt.state.save()
    return {"stalled": stalled, "recovered": recovered}


def find_long_stuck(rt: Runtime) -> dict:
    p = rt.require()
    today = rt.today()
    snaps = rt.state.data["snapshots"]
    days_desc = sorted(snaps, reverse=True)
    out = []
    for t in p.tasks:
        if t.status in CLOSED or t.status == "Task Review Pending":
            continue
        if not t.start or t.start > today:
            continue
        reasons = []
        last = t.last_update or t.start
        no_update = p.working_days_between(last, today)
        if no_update > LONG_STUCK_WORKING_DAYS:
            reasons.append(f"no update for {no_update} working days (since {iso(last)})")
        if t.status in ("On Hold", "Blocked"):
            since = None
            for d in days_desc:
                s = snaps[d].get(t.task_id)
                if not s or s["status"] != t.status:
                    break
                since = date.fromisoformat(d)
            if since:
                n = p.working_days_between(since, today)
                if n > LONG_STUCK_WORKING_DAYS:
                    reasons.append(f"{t.status} for at least {n} working days (since {iso(since)})")
        if reasons:
            out.append(t.brief() | {"why": reasons})
    already = {r["task_id"] for r in rt.rows_today(p, "Escalation")}
    pmh = p.role_person("pmh")
    return {"tasks": [t for t in out if t["task_id"] not in already],
            "already_escalated_today": sorted(already),
            "send_to": {"name": pmh, "email": p.email_of(pmh) if pmh else None}}


def pre_delivery_status(rt: Runtime, p: Optional[Project] = None) -> dict[str, Any]:
    p = p or rt.require()
    today, dd = rt.today(), p.delivery_date
    in_window = bool(dd and dd - timedelta(days=PRE_DELIVERY_WINDOW_DAYS) <= today <= dd
                     and p.is_working_day(today))
    res: dict[str, Any] = {"delivery_date": iso(dd), "in_window": in_window,
                           "email_due": False, "chat_due": False, "chat_reason": ""}
    if not in_window:
        res["chat_reason"] = "outside the window"
        return res
    pm = rt.alert_recipient(p)
    people = [pm["name"], p.role_person("delivery_lead"), p.role_person("delivery_head")]
    res["recipients"] = [{"name": n, "email": p.email_of(n)} for n in people if n]
    res["items"] = [t.brief() for t in p.tasks if t.status in ("Blocked", "On Hold")]
    sent = rt.rows_today(p, "Pre-delivery list")
    sent_mail = [r for r in sent if r["channel"] == "Email"]
    res["email_sent_today"] = bool(sent_mail)
    res["email_due"] = not sent_mail
    res["chat_sent_today"] = any(r["channel"] == "Chat" for r in sent)
    thread = rt.state.data["pre_delivery"].get(today.isoformat())
    res["acknowledged"] = bool(thread and rt.ws.thread_has_reply(thread))
    if not sent_mail:
        res["chat_reason"] = "email not sent yet"
    elif res["acknowledged"]:
        res["chat_reason"] = "email was acknowledged"
    elif res["chat_sent_today"]:
        res["chat_reason"] = "chat already sent"
    elif rt.now() < min(r["ts"] for r in sent_mail) + PRE_DELIVERY_CHAT_AFTER:
        res["chat_reason"] = "two hours have not passed since the email"
    else:
        res["chat_due"] = True
    return res
