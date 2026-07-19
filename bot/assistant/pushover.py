import httpx
from . import config

API = "https://api.pushover.net/1"


async def send_emergency(message: str, title: str = "ADHD Assistant") -> str:
    """Fire a critical alert. Returns the receipt id used to track acknowledgement."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{API}/messages.json",
            data={
                "token": config.PUSHOVER_TOKEN,
                "user": config.PUSHOVER_USER,
                "title": title,
                "message": message,
                "priority": 2,
                "retry": config.ALARM_RETRY_SECONDS,
                "expire": config.ALARM_EXPIRE_SECONDS,
                "tags": "adhd-assistant",
            },
        )
        resp.raise_for_status()
        return resp.json()["receipt"]


async def receipt_status(receipt: str) -> dict:
    """Returns {'acknowledged': 0|1, 'expired': 0|1, ...}."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{API}/receipts/{receipt}.json",
            params={"token": config.PUSHOVER_TOKEN},
        )
        resp.raise_for_status()
        return resp.json()


async def cancel(receipt: str) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            f"{API}/receipts/{receipt}/cancel.json",
            data={"token": config.PUSHOVER_TOKEN},
        )
