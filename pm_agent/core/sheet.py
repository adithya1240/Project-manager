"""The project Google Sheet: layout, parsing and the in-memory Project model."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Optional

from ..config import IST, STATUSES

TAB_INFO, TAB_TEAM, TAB_PLAN = "Project Info", "Team", "Project Plan"
TAB_HOLIDAYS, TAB_LEAVE, TAB_LOG = "Holidays", "Leave", "Activity Log"
ALL_TABS = (TAB_INFO, TAB_TEAM, TAB_PLAN, TAB_HOLIDAYS, TAB_LEAVE, TAB_LOG)

# key -> accepted header spellings (compared case- and space-insensitively)
COLUMNS: dict[str, dict[str, list[str]]] = {
    TAB_TEAM: {"name": ["Name"], "role": ["Role"], "email": ["Email"]},
    TAB_PLAN: {
        "task_id": ["Task ID"],
        "workstream": ["Workstream / Phase", "Workstream", "Phase"],
        "name": ["Task Name"],
        "owner": ["Owner"],
        "start": ["Start Date"],
        "due": ["Due Date"],
        "status": ["Status"],
        "blocked_by": ["Blocked By (Task ID)", "Blocked By"],
        "pct": ["% Complete (0-100)", "% Complete"],
        "last_update": ["Last Update Date"],
        "notes": ["Notes"],
        "blocker_details": ["Blocker Details"],
    },
    TAB_HOLIDAYS: {"date": ["Date"], "name": ["Holiday Name"]},
    TAB_LEAVE: {"name": ["Name"], "start": ["Leave Start Date"],
                "end": ["Leave End Date"], "reason": ["Reason (optional)", "Reason"]},
    TAB_LOG: {"timestamp": ["Timestamp (IST)", "Timestamp"], "task_id": ["Task ID"],
              "recipient": ["Recipient"], "channel": ["Channel"],
              "action": ["Action Type"], "summary": ["Summary"], "status": ["Status"]},
}
OPTIONAL_COLUMNS = {(TAB_LEAVE, "reason")}
# Project Plan columns the agents may write (prompt section 1).
PLAN_WRITABLE = {"pct", "last_update", "notes", "blocker_details", "status"}

INFO_FIELDS = {
    "project_name": "Project Name",
    "delivery_date": "Overall Delivery Date",
    "pm": "Project Manager",
    "pmh": "Program Manager Head",
    "delivery_lead": "Delivery Lead",
    "delivery_head": "Delivery Head",
}
PEOPLE_FIELDS = ("pm", "pmh", "delivery_lead", "delivery_head")

SHEETS_EPOCH = date(1899, 12, 30)
# Only unambiguous text formats. 03/04/2026 could be either order, so it is
# flagged rather than guessed (section 14).
DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y",
                "%b %d, %Y", "%B %d, %Y")
LOG_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


# --- parsing helpers --------------------------------------------------------

def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _info_key(s: Any) -> str:
    """'Project Manager (name)' -> 'project manager'."""
    return norm(re.sub(r"\(.*?\)", "", str(s or "")))


def parse_date(v: Any) -> Optional[date]:
    """Sheet cell -> date. Raises ValueError for anything unreadable."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ValueError(f"unreadable date {v!r}")
    if isinstance(v, (int, float)):
        return SHEETS_EPOCH + timedelta(days=int(v))
    s = str(v).strip()
    for fmt in DATE_FORMATS + (LOG_TS_FORMAT,):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unreadable date {s!r}")


def parse_timestamp(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        dt = datetime.combine(SHEETS_EPOCH, dtime()) + timedelta(days=float(v))
        return dt.replace(tzinfo=IST)
    try:
        return datetime.strptime(str(v).strip(), LOG_TS_FORMAT).replace(tzinfo=IST)
    except ValueError:
        return None


def parse_pct(v: Any) -> Optional[int]:
    """Keep the % column as a plain number format; 0.4 is read as 40."""
    if v in (None, ""):
        return None
    if isinstance(v, str):
        v = v.strip().rstrip("%").strip()
        if not v:
            return None
    f = float(v)
    if 0 < f < 1:
        f *= 100
    return int(round(f))


def col_letter(idx: int) -> str:
    s, idx = "", idx + 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def sheet_id_from_url(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", url.strip()):
        return url.strip()
    raise ValueError(f"Not a Google Sheet link: {url}")


def first_line(text: str) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def split_emails(field_value: str) -> set[str]:
    return {e.strip().lower() for e in (field_value or "").split(",") if e.strip()}


# --- model ----------------------------------------------------------------

@dataclass
class Task:
    row: int
    task_id: str
    workstream: str
    name: str
    owner: str
    start: Optional[date]
    due: Optional[date]
    status: str
    blocked_by: str
    pct: Optional[int]
    last_update: Optional[date]
    notes: str
    blocker_details: str

    def brief(self, full_notes: bool = False) -> dict:
        d = {
            "task_id": self.task_id, "name": self.name, "workstream": self.workstream,
            "owner": self.owner, "start": iso(self.start), "due": iso(self.due),
            "status": self.status, "blocked_by": self.blocked_by or None,
            "pct": self.pct, "last_update": iso(self.last_update),
            "blocker_details": self.blocker_details or None,
        }
        if full_notes:
            d["notes"] = self.notes
        else:
            d["last_note"] = first_line(self.notes) or None
        return d


@dataclass
class Project:
    info: dict[str, str] = field(default_factory=dict)       # INFO_FIELDS key -> value
    delivery_date: Optional[date] = None
    team: list[dict] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    holidays: dict[date, str] = field(default_factory=dict)
    leave: list[tuple[str, date, date, str]] = field(default_factory=list)
    log_rows: list[dict] = field(default_factory=list)
    colidx: dict[str, dict[str, int]] = field(default_factory=dict)
    header_len: dict[str, int] = field(default_factory=dict)
    fatal: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    # --- people -----------------------------------------------------------
    def person(self, name: str) -> Optional[dict]:
        n = norm(name)
        return next((p for p in self.team if norm(p["name"]) == n), None)

    def email_of(self, name: str) -> Optional[str]:
        p = self.person(name)
        return p["email"] if p and p["email"] else None

    def name_of_email(self, email: str) -> Optional[str]:
        e = (email or "").strip().lower()
        p = next((p for p in self.team if p["email"].lower() == e), None)
        return p["name"] if p else None

    def team_emails(self) -> set[str]:
        return {p["email"].lower() for p in self.team if p["email"]}

    def role_person(self, key: str) -> Optional[str]:
        return self.info.get(key) or None

    # --- calendar ---------------------------------------------------------
    def is_working_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def leave_on(self, name: str, d: date) -> Optional[tuple[date, date]]:
        n = norm(name)
        for who, s, e, _ in self.leave:
            if norm(who) == n and s <= d <= e:
                return s, e
        return None

    def working_days_between(self, a: date, b: date) -> int:
        """Working days d with a < d <= b."""
        if b <= a:
            return 0
        return sum(1 for i in range(1, (b - a).days + 1)
                   if self.is_working_day(a + timedelta(days=i)))

    # --- tasks ------------------------------------------------------------
    def task(self, task_id: str) -> Optional[Task]:
        t = norm(task_id)
        return next((x for x in self.tasks if norm(x.task_id) == t), None)

    def owner_problem(self, t: Task) -> Optional[str]:
        """Section 14 owner checks. None when the owner is usable."""
        if not t.owner.strip():
            return f"{t.task_id} has no owner"
        if re.search(r"[,/&;+]|\band\b", t.owner, re.I):
            return f"{t.task_id} has more than one owner in one cell ('{t.owner}')"
        p = self.person(t.owner)
        if not p:
            return f"{t.task_id} owner '{t.owner}' does not match any Team tab row"
        if not p["email"]:
            return f"{t.task_id} owner '{t.owner}' has no email in the Team tab"
        return None


def _header_map(tab: str, header: list[Any]) -> tuple[dict[str, int], list[str]]:
    normed = [norm(h) for h in header]
    idx, missing = {}, []
    for key, names in COLUMNS[tab].items():
        pos = next((normed.index(norm(n)) for n in names if norm(n) in normed), None)
        if pos is None:
            if (tab, key) not in OPTIONAL_COLUMNS:
                missing.append(names[0])
        else:
            idx[key] = pos
    return idx, missing


def _cell(row: list[Any], idx: dict[str, int], key: str) -> Any:
    i = idx.get(key)
    return row[i] if i is not None and i < len(row) else ""


def build_project(values: dict[str, list[list[Any]]]) -> Project:
    """Parse raw tab values into a Project, collecting fatal and minor issues.

    Team and Project Info are parsed even when another tab is broken, so the
    agents can still reach the Project Manager to report the problem."""
    p = Project()
    for tab in ALL_TABS:
        if tab not in values:
            p.fatal.append(f"Tab '{tab}' is missing")

    for tab in (TAB_TEAM, TAB_PLAN, TAB_HOLIDAYS, TAB_LEAVE, TAB_LOG):
        rows = values.get(tab)
        if rows is None:
            continue
        if not rows:
            p.fatal.append(f"Tab '{tab}' has no header row")
            continue
        idx, missing = _header_map(tab, rows[0])
        if missing:
            p.fatal.append(f"Tab '{tab}' is missing column(s): {', '.join(missing)}")
        else:
            p.colidx[tab], p.header_len[tab] = idx, len(rows[0])
    if TAB_TEAM not in p.colidx or TAB_INFO not in values:
        return p

    # Team
    ti = p.colidx[TAB_TEAM]
    for r in values[TAB_TEAM][1:]:
        name = str(_cell(r, ti, "name")).strip()
        if not name:
            continue
        p.team.append({"name": name, "role": str(_cell(r, ti, "role")).strip(),
                       "email": str(_cell(r, ti, "email")).strip()})
    for name, n in Counter(norm(x["name"]) for x in p.team).items():
        if n > 1:
            p.issues.append(f"Team tab lists '{name}' {n} times")

    # Project Info (field/value pairs)
    raw = {_info_key(r[0]): r[1] if len(r) > 1 else "" for r in values[TAB_INFO] if r}
    for key, label in INFO_FIELDS.items():
        val = str(raw.get(_info_key(label), "")).strip()
        if key == "delivery_date":
            try:
                p.delivery_date = parse_date(raw.get(_info_key(label)))
            except ValueError as e:
                p.issues.append(f"Project Info 'Overall Delivery Date': {e}")
            val = iso(p.delivery_date) or ""
        p.info[key] = val
        if not val:
            (p.fatal if key in ("project_name", "pm") else p.issues).append(
                f"Project Info field '{label}' is empty")
    for key in PEOPLE_FIELDS:
        name = p.info.get(key)
        if name and not p.email_of(name):
            (p.fatal if key == "pm" else p.issues).append(
                f"Project Info {INFO_FIELDS[key]} '{name}' is not in the Team tab with an email")
    team_pm = [x["name"] for x in p.team if norm(x["role"]) == "project manager"]
    if p.info.get("pm") and team_pm and norm(p.info["pm"]) not in map(norm, team_pm):
        p.issues.append(f"Project Info names '{p.info['pm']}' as Project Manager but the "
                        f"Team tab role Project Manager is {', '.join(team_pm)}")
    if p.fatal:
        return p

    # Holidays
    hi = p.colidx[TAB_HOLIDAYS]
    for r in values[TAB_HOLIDAYS][1:]:
        try:
            d = parse_date(_cell(r, hi, "date"))
        except ValueError as e:
            p.issues.append(f"Holidays tab: {e}")
            continue
        if d:
            p.holidays[d] = str(_cell(r, hi, "name")).strip()

    # Leave
    li = p.colidx[TAB_LEAVE]
    for r in values[TAB_LEAVE][1:]:
        name = str(_cell(r, li, "name")).strip()
        if not name:
            continue
        try:
            s, e = parse_date(_cell(r, li, "start")), parse_date(_cell(r, li, "end"))
        except ValueError as err:
            p.issues.append(f"Leave tab row for {name}: {err}")
            continue
        if not s or not e or e < s:
            p.issues.append(f"Leave tab row for {name} has missing or reversed dates")
            continue
        if not p.person(name):
            p.issues.append(f"Leave tab name '{name}' is not in the Team tab")
        p.leave.append((name, s, e, str(_cell(r, li, "reason")).strip()))

    # Project Plan
    pi = p.colidx[TAB_PLAN]
    for i, r in enumerate(values[TAB_PLAN][1:], start=2):
        tid = str(_cell(r, pi, "task_id")).strip()
        if not tid and not str(_cell(r, pi, "name")).strip():
            continue
        dates = {}
        for key in ("start", "due", "last_update"):
            try:
                dates[key] = parse_date(_cell(r, pi, key))
            except ValueError as e:
                dates[key] = None
                p.issues.append(f"{tid or f'row {i}'} {key.replace('_', ' ')}: {e}")
        try:
            pct = parse_pct(_cell(r, pi, "pct"))
        except ValueError:
            pct = None
            p.issues.append(f"{tid} % Complete is not a number")
        status = str(_cell(r, pi, "status")).strip()
        if status not in STATUSES:
            p.issues.append(f"{tid or f'row {i}'} has unknown status '{status}'")
        p.tasks.append(Task(
            row=i, task_id=tid, workstream=str(_cell(r, pi, "workstream")).strip(),
            name=str(_cell(r, pi, "name")).strip(), owner=str(_cell(r, pi, "owner")).strip(),
            start=dates["start"], due=dates["due"], status=status,
            blocked_by=str(_cell(r, pi, "blocked_by")).strip(), pct=pct,
            last_update=dates["last_update"], notes=str(_cell(r, pi, "notes")),
            blocker_details=str(_cell(r, pi, "blocker_details"))))
    for tid, n in Counter(t.task_id for t in p.tasks).items():
        if not tid:
            p.issues.append(f"{n} task row(s) have no Task ID")
        elif n > 1:
            p.issues.append(f"Task ID {tid} appears {n} times")
    for t in p.tasks:
        if t.blocked_by and not p.task(t.blocked_by):
            p.issues.append(f"{t.task_id} is Blocked By '{t.blocked_by}', which is not in the plan")

    # Activity log
    gi = p.colidx[TAB_LOG]
    for r in values[TAB_LOG][1:]:
        p.log_rows.append({k: str(_cell(r, gi, k)).strip() for k in COLUMNS[TAB_LOG]}
                          | {"ts": parse_timestamp(_cell(r, gi, "timestamp"))})
    return p
