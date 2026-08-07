from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_POLL_INTERVAL_EVENT, CONF_POLL_INTERVAL_INFO, CONF_TOKEN, CONF_UID, CONF_WIFI_SN, DOMAIN
from .coordinator import DeviceInfoCoordinator, DoorbellCoordinator, LockEventCoordinator

PLATFORMS = ["sensor", "binary_sensor", "camera"]


class KaadasApi:
    def __init__(self, hass: HomeAssistant, token: str, wifi_sn: str, uid: str) -> None:
        self._hass = hass
        self.token = token
        self.wifi_sn = wifi_sn
        self.uid = uid

    def _build_headers(self, ver: str) -> dict[str, str]:
        headers = {
            "Host": "app.kaadas.com:34000",
            "token": self.token,
            "ver": ver,
            "reqSource": "app",
            "phoneName": "iPhone 7 Plus",
            "lang": "zh_CN",
            "User-Agent": "KaadasLock/6.14.3 (iPhone; iOS 15.8.8; Scale/3.00)",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
        }
        return headers

    async def async_post(self, path: str, payload: dict[str, Any], ver: str) -> dict[str, Any]:
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(self._hass)
        headers = self._build_headers(ver)
        url = f"https://app.kaadas.com:34000{path}"
        async with session.post(url, json=payload, headers=headers, timeout=10) as response:
            if response.status != 200:
                return {"code": response.status, "data": []}
            return await response.json()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = {**entry.data, **entry.options}
    api = KaadasApi(
        hass,
        token=data[CONF_TOKEN],
        wifi_sn=data[CONF_WIFI_SN],
        uid=data[CONF_UID],
    )

    lock_event_coordinator = LockEventCoordinator(hass, entry, api, int(data.get(CONF_POLL_INTERVAL_EVENT, 10)))
    doorbell_coordinator = DoorbellCoordinator(hass, entry, api, int(data.get(CONF_POLL_INTERVAL_EVENT, 10)))
    device_info_coordinator = DeviceInfoCoordinator(hass, entry, api, int(data.get(CONF_POLL_INTERVAL_INFO, 3600)))

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "entry": entry,
        "lock_event": lock_event_coordinator,
        "doorbell": doorbell_coordinator,
        "device_info": device_info_coordinator,
        "last_doorbell_id": None,
    }

    await asyncio.gather(
        lock_event_coordinator.async_config_entry_first_refresh(),
        doorbell_coordinator.async_config_entry_first_refresh(),
        device_info_coordinator.async_config_entry_first_refresh(),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
