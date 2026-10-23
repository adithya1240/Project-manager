"""Writes to the Project Plan, limited to the section 1 allow-list.

Notes and Blocker Details are only ever prepended to, never overwritten.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from ..config import OWNER_REPORTABLE
from .runtime import Runtime
from .sheet import PLAN_WRITABLE, TAB_PLAN, Project, Task, norm


def _write(rt: Runtime, p: Project, t: Task, updates: dict[str, Any]) -> None:
    if not set(updates) <= PLAN_WRITABLE:
        raise PermissionError(f"Not writable: {set(updates) - PLAN_WRITABLE}")
    idx = p.colidx[TAB_PLAN]
    rt.ws.write_cells(rt.sheet_id, TAB_PLAN, [(t.row, idx[k], v) for k, v in updates.items()])


def _prepend(existing: str, line: str) -> str:
    return line if not existing.strip() else f"{line}\n{existing}"


def _stamp(rt: Runtime) -> str:
    return rt.now().strftime("%Y-%m-%d %H:%M")


def record_task_update(rt: Runtime, task_id: str, note: str, author_name: str,
                       percent: Optional[int], status: Optional[str], confirmed_lower: bool,
                       received_at: Optional[str], channel: str, sender_email: str) -> dict:
    p = rt.require()
    t = p.task(task_id)
    if not t:
        return {"error": f"No task {task_id} in the plan."}
    updates: dict[str, Any] = {}
    lowered = False
    if percent is not None:
        if not isinstance(percent, int) or not 0 <= percent <= 100:
            return {"error": "Percent must be a whole number 0-100; ask the owner to confirm."}
        if t.pct is not None and percent < t.pct:
            if not confirmed_lower:
                return {"error": f"{percent} is below the current {t.pct}. Ask the owner to "
                        "confirm, then call again with confirmed_lower=true."}
            lowered = True
        updates["pct"] = percent
    if status:
        if status not in OWNER_REPORTABLE:
            return {"error": f"Status from a reply can only be one of {sorted(OWNER_REPORTABLE)}."}
        final_pct = percent if percent is not None else t.pct
        if status == "Completed" and final_pct != 100:
            return {"error": "Completed needs 100% reported by the owner."}
        if status != t.status:
            updates["status"] = status
    updates["notes"] = _prepend(t.notes, f"{received_at or _stamp(rt)} - {author_name}: {note.strip()}")
    updates["last_update"] = rt.today().isoformat()
    _write(rt, p, t, updates)
    parts = [f"pct {t.pct}->{percent}" if percent is not None else "pct unchanged"]
    if "status" in updates:
        parts.append(f"status {t.status}->{status}")
    rt.log("Update recorded", f"{', '.join(parts)}. {note[:200]}",
           recipient=sender_email, channel=channel, task_ids=[t.task_id])
    return {"recorded": True, "task": t.task_id, "previous_pct": t.pct,
            "new_pct": percent if percent is not None else t.pct,
            "status": updates.get("status", t.status), "lowered_pct_tell_pm": lowered}


def append_task_note(rt: Runtime, task_id: str, note: str, author_name: str) -> dict:
    p = rt.require()
    t = p.task(task_id)
    if not t:
        return {"error": f"No task {task_id} in the plan."}
    _write(rt, p, t, {"notes": _prepend(t.notes, f"{_stamp(rt)} - {author_name}: {note.strip()}")})
    rt.log("Note added", note[:200], task_ids=[t.task_id])
    return {"recorded": True}


def set_task_blocked(rt: Runtime, task_id: str, reason: str, reported_by: str,
                     blocking_task_id: Optional[str], external_party: Optional[str]) -> dict:
    p = rt.require()
    t = p.task(task_id)
    if not t:
        return {"error": f"No task {task_id} in the plan."}
    b = p.task(blocking_task_id) if blocking_task_id else None
    if blocking_task_id and not b:
        return {"error": f"No task {blocking_task_id}. Confirm the blocking task with the reporter."}
    if b and b.task_id == t.task_id:
        return {"error": "A task cannot block itself."}
    if not b and not external_party:
        return {"error": "Give blocking_task_id, or external_party for a non-task block."}
    stamp = _stamp(rt)
    what = f"{b.task_id} '{b.name}' (owner {b.owner or 'none'})" if b else external_party
    _write(rt, p, t, {
        "status": "Blocked",
        "blocker_details": _prepend(t.blocker_details, f"{stamp}: Blocked by {what}. "
                                    f"Reason: {reason}. Reported by {reported_by}."),
        "notes": _prepend(t.notes, f"{stamp} - {reported_by}: blocked by {what}. {reason}"),
    })
    result: dict[str, Any] = {"recorded": True, "blocked_task": t.brief() | {"status": "Blocked"}}
    if b:
        _write(rt, p, b, {"notes": _prepend(
            b.notes, f"{stamp} - PM Agent: this task is blocking {t.task_id} '{t.name}' "
                     f"(owner {t.owner}).")})
        circular = (norm(b.blocked_by) == norm(t.task_id)
                    or (b.status == "Blocked" and t.task_id.lower() in b.blocker_details.lower()))
        same_owner = norm(b.owner) == norm(t.owner)
        result.update({
            "blocking_task": b.brief(), "same_owner": same_owner,
            "circular_dependency_flag_pm_now": circular,
            "blocked_owner_email": p.email_of(t.owner),
            "blocking_owner_email": p.email_of(b.owner),
            "send_joint_blocker_email": not same_owner,
            "alert_recipient": rt.alert_recipient(p, t.owner),
        })
    rt.log("Blocker recorded", f"{t.task_id} blocked by {what}: {reason}"[:300],
           task_ids=[t.task_id] + ([b.task_id] if b else []))
    return result


def clear_task_blocker(rt: Runtime, task_id: str, note: str, reported_by: str) -> dict:
    p = rt.require()
    t = p.task(task_id)
    if not t:
        return {"error": f"No task {task_id} in the plan."}
    if t.status != "Blocked":
        return {"error": f"{task_id} is {t.status}, not Blocked."}
    stamp = _stamp(rt)
    _write(rt, p, t, {
        "status": "In Progress",
        "blocker_details": _prepend(t.blocker_details, f"{stamp}: Cleared. {note}"),
        "notes": _prepend(t.notes, f"{stamp} - {reported_by}: blocker cleared. {note}"),
    })
    rt.log("Blocker cleared", note[:200], task_ids=[t.task_id])
    return {"recorded": True, "owner": t.owner, "owner_email": p.email_of(t.owner),
            "alert_recipient": rt.alert_recipient(p, t.owner)}


def add_followup_task(rt: Runtime, task_name: str, reason: str, supports_task_id: str,
                      workstream: Optional[str]) -> dict:
    p = rt.require()
    sup = p.task(supports_task_id)
    if not sup:
        return {"error": f"No task {supports_task_id} in the plan."}
    same = next((t for t in p.tasks if t.status == "Task Review Pending"
                 and norm(t.name) == norm(task_name)), None)
    if same:
        return {"error": f"Follow-up already exists as {same.task_id}.", "task_id": same.task_id}
    new_id = next_task_id([t.task_id for t in p.tasks])
    idx = p.colidx[TAB_PLAN]
    row = [""] * p.header_len[TAB_PLAN]
    for k, v in {"task_id": new_id, "workstream": workstream or sup.workstream,
                 "name": task_name, "status": "Task Review Pending",
                 "notes": f"{_stamp(rt)} - PM Agent: raised to support {sup.task_id} "
                          f"'{sup.name}'. {reason}"}.items():
        row[idx[k]] = v
    rt.ws.append_row(rt.sheet_id, TAB_PLAN, row)
    rt.log("Follow-up task added", f"{task_name} (supports {sup.task_id})", task_ids=[new_id])
    return {"added": True, "task_id": new_id,
            "next": "Send it to the Project Manager to set owner and dates.",
            "alert_recipient": rt.alert_recipient(p)}


def next_task_id(ids: list[str]) -> str:
    """Next ID in the plan's own sequence, e.g. T-006 -> T-007."""
    parsed = [m.groups() for m in (re.fullmatch(r"(.*?)(\d+)", i) for i in ids if i) if m]
    if not parsed:
        return f"FU-{len(ids) + 1}"
    prefix = Counter(pre for pre, _ in parsed).most_common(1)[0][0]
    nums = [n for pre, n in parsed if pre == prefix]
    width = max(len(n) for n in nums)
    return f"{prefix}{max(int(n) for n in nums) + 1:0{width}d}"
