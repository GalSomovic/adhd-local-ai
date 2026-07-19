import logging
from datetime import datetime

from .. import config, gapi, store

TASKS = "https://tasks.googleapis.com/tasks/v1"
LIST_TITLE = "ADHD Assistant"
log = logging.getLogger(__name__)


async def _list_id(conn):
    cached = store.kv_get(conn, "gtasks_list_id")
    if cached:
        return cached
    data = await gapi.api("GET", f"{TASKS}/users/@me/lists")
    for item in data.get("items", []) or []:
        if item["title"] == LIST_TITLE:
            store.kv_set(conn, "gtasks_list_id", item["id"])
            return item["id"]
    created = await gapi.api("POST", f"{TASKS}/users/@me/lists", json={"title": LIST_TITLE})
    store.kv_set(conn, "gtasks_list_id", created["id"])
    return created["id"]


async def add_task(conn, title, due_iso=None, notes=None):
    lid = await _list_id(conn)
    body = {"title": title}
    if due_iso:
        due = datetime.fromisoformat(due_iso)
        if due.tzinfo is None:
            due = due.replace(tzinfo=config.TZ)
        body["due"] = due.strftime("%Y-%m-%dT00:00:00.000Z")
    if notes:
        body["notes"] = notes
    created = await gapi.api("POST", f"{TASKS}/lists/{lid}/tasks", json=body)
    return created["id"]


async def complete_task(conn, task_id):
    lid = await _list_id(conn)
    await gapi.api(
        "PATCH", f"{TASKS}/lists/{lid}/tasks/{task_id}",
        json={"status": "completed"},
    )


async def list_open_tasks(conn):
    lid = await _list_id(conn)
    data = await gapi.api(
        "GET", f"{TASKS}/lists/{lid}/tasks",
        params={"showCompleted": "false"},
    )
    return [
        {"id": t["id"], "title": t.get("title", ""), "due": t.get("due")}
        for t in data.get("items", []) or []
    ]


def build(ctx):
    conn = ctx["conn"]

    async def _add(title, due_iso=None, notes=None):
        await add_task(conn, title, due_iso, notes)
        return {"confirm_to_user": f"✅ נוספה משימה: {title}"}

    async def _list():
        return {"tasks": await list_open_tasks(conn)}

    return {
        "add_task": (
            {
                "type": "function",
                "function": {
                    "name": "add_task",
                    "description": "Add a task to the user's Google Tasks (ADHD Assistant list).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "due_iso": {"type": "string", "description": "ISO date it is due"},
                            "notes": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                },
            },
            _add,
        ),
        "list_tasks": (
            {
                "type": "function",
                "function": {
                    "name": "list_tasks",
                    "description": "List open tasks from the user's Google Tasks (ADHD Assistant list).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            _list,
        ),
    }
