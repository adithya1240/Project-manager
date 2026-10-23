"""Small local state file per project.

Holds what the sheet cannot: daily % snapshots (stalled detection), processed
chat messages, the pre-delivery email thread, and the queue of blocker
hand-offs from the Reply Agent to the Blocker Agent.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config import IST

_DEFAULTS = {
    "snapshots": {},       # date -> task_id -> {pct, status, start, due}
    "date_changes": {},    # date -> [ {task_id, field, was, now} ]
    "stalled_by_day": {},  # date -> [task_id]
    "pre_delivery": {},    # date -> gmail thread id
    "chat_sent": {},       # chat message name -> iso time
    "chat_done": {},       # chat message name -> iso time
    "chat_since": None,
    "handoffs": [],        # blocker hand-offs, see core/handoffs.py
}


class State:
    def __init__(self, path: Path, persist: bool):
        self.path, self.persist = path, persist
        try:
            self.data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            self.data = {}
        for k, default in _DEFAULTS.items():
            self.data.setdefault(k, json.loads(json.dumps(default)))

    def save(self) -> None:
        if not self.persist:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, default=str), "utf-8")
        tmp.replace(self.path)

    def prune(self, today: date) -> None:
        cutoff = (today - timedelta(days=60)).isoformat()
        for k in ("snapshots", "date_changes", "stalled_by_day", "pre_delivery"):
            self.data[k] = {d: v for d, v in self.data[k].items() if d >= cutoff}
        week = (datetime.now(IST) - timedelta(days=7)).isoformat()
        for k in ("chat_sent", "chat_done"):
            self.data[k] = {n: t for n, t in self.data[k].items() if t >= week}
        self.data["handoffs"] = [h for h in self.data["handoffs"]
                                 if not h.get("done_at") or h["done_at"] >= week]
