from __future__ import annotations

import logging

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import ALARM_ENDPOINT

from .const import DOMAIN, EVENT_ENDPOINT, DEVICE_INFO_ENDPOINT, DOORBELL_ENDPOINT


class LockEventCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry, api, interval: int, state=None) -> None:
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),  # ✅ 已修复
            name="kaadas_lock_event",
            update_interval=timedelta(seconds=interval),
        )
        self._entry = entry
        self._api = api
        self.state = state
        self.data = {}

    async def _async_update_data(self) -> dict[str, Any]:
        payload = {"wifiSN": self._api.wifi_sn, "page": 1}
        result = await self._api.async_post(EVENT_ENDPOINT, payload, "20230913")
        data = records(result)
        if self.state:
            await self.state.process("operation", data)
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
            logger=logging.getLogger(__name__),  # ← 这里改了
            name="kaadas_doorbell",
            update_interval=timedelta(seconds=interval),
        )
        self._entry = entry
        self._api = api
        self.data = {}

    async def _async_update_data(self) -> dict[str, Any]:
        payload = {"wifiSN": self._api.wifi_sn, "page": 1}
        result = await self._api.async_post(DOORBELL_ENDPOINT, payload, "20230913")
        data = records(result)
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
            logger=logging.getLogger(__name__),  # ← 这里改了
            name="kaadas_device_info",
            update_interval=timedelta(seconds=interval),
        )
        self._entry = entry
        self._api = api
        self.data = {}

    async def _async_update_data(self) -> dict[str, Any]:
        payload = {"uid": self._api.uid, "modelSearchType": 2}
        result = await self._api.async_post(DEVICE_INFO_ENDPOINT, payload, "20231127")
        body = result.get("data")
        if not isinstance(body, dict) or not isinstance(body.get("wifiList"), list):
            raise UpdateFailed("Invalid device response")
        wifi_list = body["wifiList"]
        # 自动登录可从多台绑定门锁中选择一台；同一账号下必须关联到所选wifiSN。
        device = next((d for d in wifi_list if isinstance(d, dict) and
                       str(d.get("wifiSN") or "") == str(self._api.wifi_sn)),
                      wifi_list[0] if len(wifi_list) == 1 else {})
        from homeassistant.helpers import device_registry as dr
        registry = dr.async_get(self.hass)
        device_entry = registry.async_get_device(identifiers={(DOMAIN, self._entry.entry_id)})
        settings = {**self._entry.data, **self._entry.options}
        if device_entry:
            registry.async_update_device(device_entry.id, name=settings.get("display_name") or device.get("lockNickname") or "凯迪仕门锁")
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


def records(result):
    data = result.get("data")
    if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
        raise UpdateFailed("Invalid Kaadas record list")
    return data


class AlarmCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, api, interval, state):
        super().__init__(hass, logging.getLogger(__name__), name="kaadas_alarm", update_interval=timedelta(seconds=interval))
        self._api, self.state = api, state
        self.data = {}

    async def _async_update_data(self):
        result = await self._api.async_post(ALARM_ENDPOINT, {"wifiSN": self._api.wifi_sn, "page": 1}, "20231127")
        await self.state.process("alarm", records(result))
        alarm = self.state.engine.data.get("alarm") or {}
        latest = alarm.get("latest") or {}
        return {"time": latest.get("time"), "text_content": latest.get("textContent"), "timestamp": alarm.get("watermark") if latest else None, "text_title": latest.get("textTitle"), "warning_type": latest.get("type"), "create_time": latest.get("createTime")}
