"""Kaadas HTTP client, retaining endpoint versions and JSON bodies."""
from __future__ import annotations

import asyncio
import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import API_BASE_URL, EVENT_ENDPOINT, DOORBELL_ENDPOINT, DEVICE_INFO_ENDPOINT, ALARM_ENDPOINT

ENDPOINT_NAMES = {EVENT_ENDPOINT: "event", DOORBELL_ENDPOINT: "doorbell", DEVICE_INFO_ENDPOINT: "info", ALARM_ENDPOINT: "alarm"}
VERSIONS = {"event": "20230913", "doorbell": "20230913", "info": "20231127", "alarm": "20231127"}
HEADER_FIELDS = {"token": "token", "user_agent": "User-Agent", "phone_name": "phoneName", "req_source": "reqSource", "lang": "lang"}


class KaadasApi:
    def __init__(self, hass, token, wifi_sn, uid, user_agent, phone_name, settings=None):
        self._hass = hass
        self.token, self.wifi_sn, self.uid = token, wifi_sn, uid
        self.user_agent, self.phone_name = user_agent, phone_name
        self.settings = settings or {}

    def _build_headers(self, ver, endpoint=None):
        headers = {"Host": "app.kaadas.com:34000", "token": self.token, "ver": ver, "reqSource": "app", "phoneName": self.phone_name, "lang": "zh_CN", "User-Agent": self.user_agent, "Connection": "keep-alive", "Content-Type": "application/json"}
        override = self.settings.get("headers", {}).get(ENDPOINT_NAMES.get(endpoint), {})
        for field, header in HEADER_FIELDS.items():
            if override.get(field):
                headers[header] = override[field]
        if endpoint == ALARM_ENDPOINT:
            headers["ver"] = self.settings.get("alarm_ver", "20231127")
        return headers

    async def async_post(self, path, payload, ver):
        try:
            async with async_get_clientsession(self._hass).post(API_BASE_URL + path, json=payload, headers=self._build_headers(ver, path), timeout=10) as response:
                if response.status != 200:
                    raise UpdateFailed(f"Kaadas HTTP {response.status}")
                result = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise UpdateFailed("Kaadas request failed or returned invalid JSON") from None
        if not isinstance(result, dict):
            raise UpdateFailed("Kaadas response is not an object")
        if result.get("success") is False or str(result.get("code", 0)) not in ("0", "200", "None"):
            # Never expose the server message, headers or response body to logs.
            raise UpdateFailed("Kaadas API reported an error; check endpoint credentials")
        return result
