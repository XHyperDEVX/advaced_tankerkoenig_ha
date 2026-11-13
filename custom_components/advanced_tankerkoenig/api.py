"""Small API client; never expose request URLs containing the API key."""
from __future__ import annotations

import asyncio
import json

from aiohttp import ClientError, ClientTimeout
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import API_BASE


class AdvancedTankerkoenigApi:
    def __init__(self, session, api_key: str):
        self._session = session
        self._api_key = api_key

    async def request(self, endpoint: str, **params) -> dict:
        try:
            async with self._session.get(
                f"{API_BASE}/{endpoint}.php",
                params={**params, "apikey": self._api_key},
                timeout=ClientTimeout(total=25),
                allow_redirects=False,
            ) as response:
                # Do not stringify aiohttp exceptions: they can contain the key.
                if not 200 <= response.status < 300:
                    raise UpdateFailed(f"Tankerkönig API: HTTP {response.status}")
                payload = await response.json(content_type=None)
        except (ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Tankerkönig API nicht erreichbar ({type(err).__name__})") from None
        except (ValueError, UnicodeError, json.JSONDecodeError):
            raise UpdateFailed("Tankerkönig API: ungültiges JSON") from None
        if not isinstance(payload, dict):
            raise UpdateFailed("Tankerkönig API: ungültige Antwort")
        if payload.get("ok") is not True:
            message = str(payload.get("message") or "Unbekannter API-Fehler")
            message = message.replace(self._api_key, "[REDACTED]")
            raise UpdateFailed(f"Tankerkönig API: {message}")
        return payload
