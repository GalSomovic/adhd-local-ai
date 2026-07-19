"""Minimal Google API client: refresh-token auth + one call helper. No SDK."""

import time

import httpx

from . import config

_token = {"value": None, "exp": 0.0}


def enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_REFRESH_TOKEN)


async def _access_token() -> str:
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "refresh_token": config.GOOGLE_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    _token["value"] = data["access_token"]
    _token["exp"] = time.time() + data.get("expires_in", 3600)
    return _token["value"]


async def api(method: str, url: str, **kwargs):
    token = await _access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}
