import base64
import json
import re
from email.mime.text import MIMEText

from .. import gapi, store

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
BODY_LIMIT = 3500


def _headers(msg, *names):
    hs = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return [hs.get(n.lower(), "") for n in names]


def _extract_body(payload):
    if payload.get("mimeType", "").startswith("text/") and payload.get("body", {}).get("data"):
        text = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
        if payload["mimeType"] == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s{2,}", " ", text)
        return text
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            got = _extract_body(part)
            if got:
                return got
    for part in payload.get("parts", []) or []:
        got = _extract_body(part)
        if got:
            return got
    return ""


async def search_emails(query="is:unread newer_than:1d in:inbox", max_results=10):
    listing = await gapi.api(
        "GET", f"{GMAIL}/messages", params={"q": query, "maxResults": max_results}
    )
    out = []
    for ref in listing.get("messages", []) or []:
        msg = await gapi.api(
            "GET",
            f"{GMAIL}/messages/{ref['id']}",
            params={
                "format": "metadata",
                "metadataHeaders": ["From", "Subject", "Date"],
            },
        )
        sender, subject, date = _headers(msg, "From", "Subject", "Date")
        out.append(
            {
                "id": ref["id"],
                "from": sender,
                "subject": subject,
                "date": date,
                "snippet": msg.get("snippet", ""),
            }
        )
    return out


async def read_email(message_id):
    msg = await gapi.api("GET", f"{GMAIL}/messages/{message_id}", params={"format": "full"})
    sender, subject, date = _headers(msg, "From", "Subject", "Date")
    body = _extract_body(msg.get("payload", {}))[:BODY_LIMIT]
    return {"from": sender, "subject": subject, "date": date, "body": body}


def stage_draft(conn, to, subject, body):
    store.kv_set(conn, "staged_draft", json.dumps(
        {"to": to, "subject": subject, "body": body}, ensure_ascii=False))
    return {
        "confirm_to_user": (
            f"📧 טיוטה מוכנה (לא נשלחה!)\n"
            f"אל: {to}\nנושא: {subject}\n---\n{body}\n---\n"
            f"לשליחה: !send | לביטול: !discard"
        )
    }


async def send_staged(conn):
    raw = store.kv_get(conn, "staged_draft")
    if not raw:
        return "אין טיוטה ממתינה"
    draft = json.loads(raw)
    mime = MIMEText(draft["body"], "plain", "utf-8")
    mime["to"] = draft["to"]
    mime["subject"] = draft["subject"]
    encoded = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    await gapi.api("POST", f"{GMAIL}/messages/send", json={"raw": encoded})
    store.kv_set(conn, "staged_draft", "")
    return f"נשלח ✉️✅ אל {draft['to']}"


def discard_staged(conn):
    store.kv_set(conn, "staged_draft", "")
    return "הטיוטה בוטלה 🗑️"


def build(ctx):
    conn = ctx["conn"]

    async def _search(query=None, max_results=10):
        return {"emails": await search_emails(query or "is:unread newer_than:1d in:inbox",
                                              min(int(max_results), 15))}

    async def _read(message_id):
        return await read_email(message_id)

    async def _draft(to, subject, body):
        return stage_draft(conn, to, subject, body)

    return {
        "search_emails": (
            {
                "type": "function",
                "function": {
                    "name": "search_emails",
                    "description": (
                        "Search Gmail. query uses Gmail syntax (e.g. 'is:unread', "
                        "'from:someone newer_than:7d'). Returns sender/subject/snippet "
                        "per message. Default: unread from the last day."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {"type": "integer"},
                        },
                    },
                },
            },
            _search,
        ),
        "read_email": (
            {
                "type": "function",
                "function": {
                    "name": "read_email",
                    "description": "Read the full body of one email by its id (from search_emails).",
                    "parameters": {
                        "type": "object",
                        "properties": {"message_id": {"type": "string"}},
                        "required": ["message_id"],
                    },
                },
            },
            _read,
        ),
        "draft_email": (
            {
                "type": "function",
                "function": {
                    "name": "draft_email",
                    "description": (
                        "Stage an outgoing email as a DRAFT. It is NEVER sent by you — "
                        "the user must approve with !send. Never claim an email was sent."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string"},
                            "subject": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["to", "subject", "body"],
                    },
                },
            },
            _draft,
        ),
    }
