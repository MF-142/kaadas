import logging

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, EVENT_ENDPOINT, DEVICE_INFO_ENDPOINT, DOORBELL_ENDPOINT


class LockEventCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry, api, interval: int) -> None:
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name="kaadas_lock_event",
            update_interval=timedelta(seconds=interval),
        )
        self._entry = entry
        self._api = api

    async def _async_update_data(self) -> dict[str, Any]:
        payload = {"wifiSN": self._api.wifi_sn, "page": 1}
        result = await self._api.async_post(EVENT_ENDPOINT, payload, "20230913")
        data = result.get("data") or []
        latest = data[0] if data else {}
        return {
            "last_time": latest.get("time"),
            "last_text_content": latest.get("textContent"),
            "last_pwd_num": latest.get("pwdNum"),
            "last_pwd_nickname": latest.get("userNickname"),
        }


class DoorbellCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry, api, interval: int) -> None:
        super().__init__(
            hass,
            logger=hass.logger,
            name="kaadas_doorbell",
            update_interval=timedelta(seconds=interval),
        )
        self._entry = entry
        self._api = api

    async def _async_update_data(self) -> dict[str, Any]:
        payload = {"wifiSN": self._api.wifi_sn, "page": 1}
        result = await self._api.async_post(DOORBELL_ENDPOINT, payload, "20230913")
        data = result.get("data") or []
        latest = data[1] if len(data) > 1 else (data[0] if data else {})
        return {
            "event_id": latest.get("eventId"),
            "thumb_url": latest.get("thumbUrl"),
            "text_content": latest.get("textContent"),
            "time": latest.get("time"),
        }


class DeviceInfoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry, api, interval: int) -> None:
        super().__init__(
            hass,
            logger=hass.logger,
            name="kaadas_device_info",
            update_interval=timedelta(seconds=interval),
        )
        self._entry = entry
        self._api = api

    async def _async_update_data(self) -> dict[str, Any]:
        payload = {"uid": self._api.uid, "modelSearchType": 2}
        result = await self._api.async_post(DEVICE_INFO_ENDPOINT, payload, "20231127")
        wifi_list = (result.get("data") or {}).get("wifiList") or []
        device = wifi_list[0] if wifi_list else {}
        return {
            "product_model": device.get("productModel"),
            "lock_nickname": device.get("lockNickname"),
            "admin_name": device.get("adminName"),
            "wifi_address": device.get("wifiAddress"),
            "camera_version": device.get("camera_version"),
            "wifi_name": device.get("wifiName"),
            "power": device.get("power"),
            "open_count": device.get("openCount"),
        }
