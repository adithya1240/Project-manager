"""Google Workspace access (Sheets, Gmail, Chat), acting as the agent mailbox.

This is the only module that talks to Google. With dry_run=True every write and
send is printed instead of performed; reads still hit the real APIs.
"""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Any, Optional

from ..config import IST, SCOPES, Config
from .sheet import ALL_TABS, col_letter


class Workspace:
    def __init__(self, cfg: Config, dry_run: bool = False):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            cfg.service_account_file, scopes=SCOPES).with_subject(cfg.agent_mailbox)
        self.mailbox = cfg.agent_mailbox.lower()
        self.dry_run = dry_run
        self.sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self.chat = build("chat", "v1", credentials=creds, cache_discovery=False)
        self._dm_cache: dict[str, Optional[str]] = {}
        self._label_ids: dict[str, str] = {}

    # --- Sheets -----------------------------------------------------------
    def read_tabs(self, sheet_id: str) -> dict[str, list[list[Any]]]:
        meta = self.sheets.spreadsheets().get(
            spreadsheetId=sheet_id, fields="sheets.properties.title").execute()
        titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
        present = [t for t in ALL_TABS if t in titles]
        if not present:
            return {}
        res = self.sheets.spreadsheets().values().batchGet(
            spreadsheetId=sheet_id, ranges=[f"'{t}'" for t in present],
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="SERIAL_NUMBER").execute()
        return {t: vr.get("values", []) for t, vr in zip(present, res["valueRanges"])}

    def write_cells(self, sheet_id: str, tab: str, cells: list[tuple[int, int, Any]]) -> None:
        """cells: (row number, 0-based column, value). Written RAW, never as formulas."""
        data = [{"range": f"'{tab}'!{col_letter(c)}{r}", "values": [[v]]} for r, c, v in cells]
        if self.dry_run:
            for d in data:
                print(f"[DRY-RUN] write {d['range']} = {d['values'][0][0]!r}")
            return
        self.sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id, body={"valueInputOption": "RAW", "data": data}).execute()

    def append_row(self, sheet_id: str, tab: str, row: list[Any]) -> None:
        if self.dry_run:
            print(f"[DRY-RUN] append to '{tab}': {row}")
            return
        self.sheets.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=f"'{tab}'!A1", valueInputOption="RAW",
            insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()

    # --- Gmail ------------------------------------------------------------
    def send_email(self, to: list[str], cc: list[str], subject: str, body: str,
                   reply_to: Optional[dict] = None) -> tuple[str, str]:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.mailbox
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        payload: dict[str, Any] = {}
        if reply_to:
            if reply_to.get("message_id"):
                msg["In-Reply-To"] = reply_to["message_id"]
                msg["References"] = reply_to["message_id"]
            payload["threadId"] = reply_to["thread_id"]
        if self.dry_run:
            print(f"[DRY-RUN] EMAIL to={to} cc={cc}\n  Subject: {subject}\n"
                  + "\n".join("  | " + ln for ln in body.splitlines()))
            return "dry-run", reply_to["thread_id"] if reply_to else "dry-run-thread"
        payload["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        res = self.gmail.users().messages().send(userId="me", body=payload).execute()
        return res["id"], res["threadId"]

    def _label_id(self, name: str) -> str:
        if name in self._label_ids:
            return self._label_ids[name]
        labels = self.gmail.users().labels().list(userId="me").execute().get("labels", [])
        lid = next((l["id"] for l in labels if l["name"].lower() == name.lower()), None)
        if not lid and not self.dry_run:
            lid = self.gmail.users().labels().create(
                userId="me", body={"name": name, "labelListVisibility": "labelHide",
                                   "messageListVisibility": "hide"}).execute()["id"]
        self._label_ids[name] = lid or ""
        return self._label_ids[name]

    def unprocessed_emails(self, label: str, days: int) -> list[dict]:
        q = f"in:inbox newer_than:{days}d -from:me -label:{label}"
        out, token = [], None
        while True:
            res = self.gmail.users().messages().list(
                userId="me", q=q, maxResults=100, pageToken=token).execute()
            for m in res.get("messages", []):
                full = self.gmail.users().messages().get(
                    userId="me", id=m["id"], format="full").execute()
                out.append(_parse_gmail(full))
            token = res.get("nextPageToken")
            if not token:
                return sorted(out, key=lambda x: x["received_at"])

    def email_reply_ref(self, gmail_id: str) -> dict:
        m = self.gmail.users().messages().get(
            userId="me", id=gmail_id, format="metadata",
            metadataHeaders=["Message-ID", "Subject"]).execute()
        hdr = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        return {"thread_id": m["threadId"], "message_id": hdr.get("message-id"),
                "subject": hdr.get("subject", "")}

    def mark_email_processed(self, gmail_id: str, label: str) -> None:
        if self.dry_run:
            print(f"[DRY-RUN] label gmail:{gmail_id} as {label}")
            return
        self.gmail.users().messages().modify(
            userId="me", id=gmail_id, body={"addLabelIds": [self._label_id(label)]}).execute()

    def thread_has_reply(self, thread_id: str) -> bool:
        if not thread_id or thread_id.startswith("dry-run"):
            return False
        t = self.gmail.users().threads().get(
            userId="me", id=thread_id, format="metadata", metadataHeaders=["From"]).execute()
        for m in t.get("messages", []):
            hdr = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
            if parseaddr(hdr.get("from", ""))[1].lower() != self.mailbox:
                return True
        return False

    # --- Chat -------------------------------------------------------------
    def dm_space(self, email: str, create: bool) -> Optional[str]:
        from googleapiclient.errors import HttpError
        key = email.lower()
        if self._dm_cache.get(key):
            return self._dm_cache[key]
        try:
            sp = self.chat.spaces().findDirectMessage(name=f"users/{key}").execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise
            if not create:
                return None
            sp = self.chat.spaces().setup(body={
                "space": {"spaceType": "DIRECT_MESSAGE"},
                "memberships": [{"member": {"name": f"users/{key}", "type": "HUMAN"}}],
            }).execute()
        self._dm_cache[key] = sp["name"]
        return sp["name"]

    def send_chat(self, email: str, text: str) -> dict:
        if self.dry_run:
            print(f"[DRY-RUN] CHAT to {email}\n" + "\n".join("  | " + ln for ln in text.splitlines()))
            return {"name": "dry-run", "sender": {}}
        space = self.dm_space(email, create=True)
        return self.chat.spaces().messages().create(parent=space, body={"text": text}).execute()

    def chat_messages_since(self, email: str, since: datetime) -> list[dict]:
        space = self.dm_space(email, create=False)
        if not space:
            return []
        stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out, token = [], None
        while True:
            res = self.chat.spaces().messages().list(
                parent=space, filter=f'createTime > "{stamp}"', pageSize=100,
                pageToken=token).execute()
            out.extend(res.get("messages", []))
            token = res.get("nextPageToken")
            if not token:
                return out


def _gmail_text(payload: dict) -> str:
    """First text/plain part; falls back to tag-stripped HTML."""
    def walk(part: dict, mime: str) -> Optional[str]:
        if part.get("mimeType") == mime and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            found = walk(sub, mime)
            if found:
                return found
        return None
    text = walk(payload, "text/plain")
    if text is None:
        h = walk(payload, "text/html") or ""
        text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?i)<br\s*/?>|</p>", "\n", h)))
    return text


def _strip_quoted(text: str) -> str:
    keep = []
    for ln in text.splitlines():
        if re.match(r"^\s*On .+wrote:\s*$", ln) or ln.strip().startswith(
                ("-----Original Message-----", "________________")):
            break
        if ln.lstrip().startswith(">"):
            continue
        keep.append(ln)
    return "\n".join(keep).strip()


def _parse_gmail(m: dict) -> dict:
    hdr = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
    sender_name, sender = parseaddr(hdr.get("from", ""))
    subject = hdr.get("subject", "")
    auto = (hdr.get("auto-submitted", "no").lower() != "no"
            or "x-autoreply" in hdr or "x-autorespond" in hdr
            or hdr.get("precedence", "").lower() in ("auto_reply", "bulk", "junk")
            or re.match(r"(?i)^(automatic reply|auto:|out of (the )?office|autoreply)", subject))
    bounce = sender.lower().startswith(("mailer-daemon", "postmaster"))
    return {
        "reply_id": f"gmail:{m['id']}", "channel": "Email",
        "sender_email": sender.lower(), "sender_display_name": sender_name,
        "received_at": datetime.fromtimestamp(int(m["internalDate"]) / 1000, IST),
        "subject": subject, "text": _strip_quoted(_gmail_text(m["payload"]))[:4000],
        "is_auto_reply": bool(auto), "is_bounce": bounce,
    }


def parse_rfc3339(s: str) -> datetime:
    s = re.sub(r"(\.\d{6})\d+", r"\1", s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)
