from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    CONF_PHONE_NAME,
    CONF_POLL_INTERVAL_EVENT,
    CONF_POLL_INTERVAL_INFO,
    CONF_TOKEN,
    CONF_UID,
    CONF_USER_AGENT,
    CONF_WIFI_SN,
    DOMAIN,
)
from .coordinator import DeviceInfoCoordinator, DoorbellCoordinator, LockEventCoordinator

PLATFORMS = ["sensor", "binary_sensor", "image"]


from .api import KaadasApi
from .runtime import StateManager
from .coordinator import AlarmCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = {**entry.data, **entry.options}

    if CONF_USER_AGENT not in data or CONF_PHONE_NAME not in data:
        raise ConfigEntryAuthFailed("缺少 User-Agent 和 phoneName，请删除集成后重新配置")

    api = KaadasApi(
        hass,
        token=data[CONF_TOKEN],
        wifi_sn=data[CONF_WIFI_SN],
        uid=data[CONF_UID],
        user_agent=data[CONF_USER_AGENT],
        phone_name=data[CONF_PHONE_NAME],
        settings=data,
    )

    state = StateManager(hass, entry, data)
    await state.load()

    lock_event_coordinator = LockEventCoordinator(hass, entry, api, int(data.get(CONF_POLL_INTERVAL_EVENT, 5)), state)
    doorbell_coordinator = DoorbellCoordinator(hass, entry, api, int(data.get("poll_interval_doorbell", 10)))
    device_info_coordinator = DeviceInfoCoordinator(hass, entry, api, int(data.get(CONF_POLL_INTERVAL_INFO, 14400)))
    alarm_coordinator = AlarmCoordinator(hass, entry, api, int(data.get("poll_interval_alarm", 5)), state)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "state": state,
        "alarm": alarm_coordinator,
        "entry": entry,
        "lock_event": lock_event_coordinator,
        "doorbell": doorbell_coordinator,
        "device_info": device_info_coordinator,
        "last_doorbell_id": None,
    }

    await asyncio.gather(
        lock_event_coordinator.async_refresh(),
        doorbell_coordinator.async_refresh(),
        device_info_coordinator.async_refresh(),
        alarm_coordinator.async_refresh(),
    )

    # Remove obsolete fixed-number entities and removed/disabled member entities only.
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    active = {f"{entry.entry_id}_member_{m['id']}" for m in data.get("members", []) if m.get("feedback", True)}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (entity.unique_id.startswith(f"{entry.entry_id}_member_") and entity.unique_id not in active) or entity.unique_id in {f"{entry.entry_id}_user_{i}" for i in range(1, 5)} | {f"{entry.entry_id}_inside"}:
            registry.async_remove(entity.entity_id)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


# 账号登录测试器 v0.2.0 的临时图形验证码图片端点（独立于门锁业务轮询）。
import secrets
import time
from aiohttp import web
from homeassistant.components.http import HomeAssistantView

_CAPTCHA_STORE = "kaadas_auth_captchas"


class KaadasCaptchaView(HomeAssistantView):
    url = "/api/kaadas/captcha/{token}"
    name = "api:kaadas:captcha"
    # 临时高熵URL；有效期5分钟，图片不含登录凭证。与已验证测试器保持一致。
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, token: str) -> web.Response:
        storage = self._hass.data.get(_CAPTCHA_STORE, {})
        item = storage.get(token)
        if item is None or time.monotonic() > item["expires"]:
            storage.pop(token, None)
            return web.Response(status=404)
        return web.Response(
            body=item["bytes"], content_type="image/jpeg",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )


def ensure_captcha_view(hass: HomeAssistant) -> None:
    """ConfigFlow may run before the integration has an installed config entry."""
    if not hass.data.get("kaadas_captcha_view_registered", False):
        hass.http.register_view(KaadasCaptchaView(hass))
        hass.data["kaadas_captcha_view_registered"] = True


def put_captcha(hass: HomeAssistant, jpeg: bytes) -> str:
    ensure_captcha_view(hass)
    storage = hass.data.setdefault(_CAPTCHA_STORE, {})
    for key in list(storage):
        if storage[key]["expires"] <= time.monotonic():
            storage.pop(key, None)
    token = secrets.token_urlsafe(36)
    storage[token] = {"expires": time.monotonic() + 300, "bytes": jpeg}
    return f"/api/kaadas/captcha/{token}"


def remove_captcha(hass: HomeAssistant, url: str | None) -> None:
    if url:
        hass.data.get(_CAPTCHA_STORE, {}).pop(url.rsplit("/", 1)[-1], None)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    hass.data.setdefault(_CAPTCHA_STORE, {})
    ensure_captcha_view(hass)
    # The member editor is optional UI: a frontend registration failure must not
    # prevent the existing read-only door-lock integration from starting.
    try:
        from .members_panel import async_register_members_panel
        await async_register_members_panel(hass)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("成员管理页面初始化失败；门锁业务仍将正常加载")
    return True
