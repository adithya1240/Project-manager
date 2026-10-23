"""Runtime: one project sheet, one clock, one activity log, shared by all agents in a run."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from ..config import IST, SENT_OK, Config
from .sheet import COLUMNS, LOG_TS_FORMAT, TAB_LOG, Project, build_project, norm, \
    sheet_id_from_url, split_emails
from .state import State
from .workspace import Workspace

log = logging.getLogger("pm_agent")


class Runtime:
    def __init__(self, cfg: Config, ws: Workspace, sheet_url: str,
                 now: Optional[datetime] = None):
        self.cfg, self.ws = cfg, ws
        self.sheet_url = sheet_url
        self.sheet_id = sheet_id_from_url(sheet_url)
        self.label = f"PMA-{self.sheet_id[:12]}"   # Gmail label: replies processed for this project
        self.state = State(cfg.state_dir / f"{self.sheet_id}.json", persist=not ws.dry_run)
        self._fixed_now = now
        self._p: Optional[Project] = None
        self.dry_log: list[dict] = []     # log rows written during a dry run
        self.dry_done: set[str] = set()   # replies "processed" during a dry run

    # --- clock & data -----------------------------------------------------
    def now(self) -> datetime:
        return self._fixed_now or datetime.now(IST)

    def today(self) -> date:
        return self.now().date()

    def project(self, refresh: bool = False) -> Project:
        if self._p is None or refresh:
            try:
                values = self.ws.read_tabs(self.sheet_id)
            except Exception as e:  # missing, locked, no access
                p = Project()
                p.fatal.append(f"Cannot open the project sheet: {e}")
                self._p = p
                return p
            self._p = build_project(values)
            self._p.log_rows.extend(self.dry_log)
        return self._p

    def require(self) -> Project:
        """Fresh project data, or an error if the sheet must not be acted on."""
        p = self.project(refresh=True)
        if p.fatal:
            raise RuntimeError("Sheet problems, act on nothing: " + "; ".join(p.fatal))
        return p

    # --- activity log -----------------------------------------------------
    def log(self, action: str, summary: str, *, recipient: str = "", channel: str = "Email",
            status: str = "Recorded", task_ids: tuple[str, ...] | list[str] = ()) -> None:
        """Append one Activity Log row per task (or one blank-task row)."""
        p = self.project()
        ts = self.now().replace(microsecond=0)
        for tid in (list(task_ids) or [""]):
            rec = {"timestamp": ts.strftime(LOG_TS_FORMAT), "task_id": tid,
                   "recipient": recipient, "channel": channel, "action": action,
                   "summary": summary[:500], "status": status}
            if p.colidx.get(TAB_LOG):
                row = [""] * p.header_len[TAB_LOG]
                for k, i in p.colidx[TAB_LOG].items():
                    row[i] = rec[k]
                self.ws.append_row(self.sheet_id, TAB_LOG, row)
            else:
                log.warning("Activity Log unavailable, not written: %s", rec)
            rec["ts"] = ts
            p.log_rows.append(rec)
            if self.ws.dry_run:
                self.dry_log.append(rec)

    def rows_today(self, p: Project, action: Optional[str] = None,
                   ok_only: bool = True) -> list[dict]:
        today = self.today()
        return [r for r in p.log_rows if r["ts"] and r["ts"].date() == today
                and (action is None or r["action"] == action)
                and (not ok_only or r["status"] in SENT_OK)]

    def replied_since(self, p: Project, email: str, since: datetime) -> bool:
        return any(r["action"] == "Reply received" and email in split_emails(r["recipient"])
                   and r["ts"] and r["ts"] >= since for r in p.log_rows)

    def search_log(self, task_id: str, action: str, recipient: str, since: datetime) -> list[dict]:
        p = self.require()
        return [{k: r[k] for k in COLUMNS[TAB_LOG]} for r in p.log_rows
                if r["ts"] and r["ts"] >= since
                and (not task_id or norm(r["task_id"]) == norm(task_id))
                and (not action or norm(r["action"]) == norm(action))
                and (not recipient or recipient.lower() in r["recipient"].lower())][-100:]

    # --- routing ----------------------------------------------------------
    def alert_recipient(self, p: Project, about_owner: Optional[str] = None) -> dict[str, Any]:
        """Sections 12 and 14: the PM, or the Program Manager Head when the PM is on
        leave or is the owner of the task the alert is about."""
        pm, pmh = p.role_person("pm"), p.role_person("pmh")
        reason = None
        if pm and p.leave_on(pm, self.today()):
            reason = "Project Manager is on leave"
        elif about_owner and pm and norm(about_owner) == norm(pm):
            reason = "the task owner is the Project Manager"
        name = pmh if reason and pmh else pm
        return {"name": name, "email": p.email_of(name) if name else None,
                "routed_to_program_manager_head": bool(reason and pmh), "reason": reason}
