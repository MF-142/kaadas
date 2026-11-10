"""Durable state changes, followed by Home Assistant events."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone

from homeassistant.components import persistent_notification
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .state import EventState


class StateManager:
    def __init__(self, hass, entry, settings):
        self.hass, self.entry, self.settings = hass, entry, settings
        self.store = Store(hass, 1, f"kaadas.{entry.entry_id}.events")
        self.lock = asyncio.Lock()
        self.engine = None

    async def load(self):
        saved = await self.store.async_load()
        self.engine = EventState(saved, dt_util.get_time_zone(self.settings.get("event_timezone", "Asia/Shanghai")) or timezone.utc)
        enabled = {m["id"] for m in self.settings.get("members", []) if m.get("feedback", True)}
        self.engine.data["members"] = {key: value for key, value in self.engine.data["members"].items() if key in enabled}
        if saved and saved != self.engine.data:
            await self.store.async_save(self.engine.data)

    async def process(self, kind, records):
        async with self.lock:
            previous = deepcopy(self.engine.data)
            was_alarm_ready = self.engine.alarm_ready
            now = datetime.now(timezone.utc).timestamp()
            if kind == "alarm":
                events = self.engine.alarms(records, now)
            else:
                events = self.engine.operations(records, self.settings.get("members", []), now, self.settings)
            if previous != self.engine.data:
                try:
                    await self.store.async_save(self.engine.data)
                except Exception:
                    self.engine.data = previous
                    self.engine.alarm_ready = was_alarm_ready
                    raise
        for event in events:
            data = {**event, "entry_id": self.entry.entry_id}
            event_type = data.pop("type")
            notify = data.pop("notify", self.settings.get("alarm_notify", True))
            self.hass.bus.async_fire(event_type, data)
            if notify:
                suffix = "alarm" if kind == "alarm" else data["member_id"]
                title = "凯迪仕预警信息" if kind == "alarm" else f"{data['member_name']} 开门反馈"
                persistent_notification.async_create(self.hass, f"{data.get('text_content') or ''}\n时间：{data['time']}", title, f"kaadas_{self.entry.entry_id}_{suffix}")


def device_info(hass, entry):
    runtime = hass.data.get("kaadas", {}).get(entry.entry_id, {})
    info = runtime.get("device_info")
    settings = {**entry.data, **entry.options}
    nickname = (info.data or {}).get("lock_nickname") if info else None
    return {"identifiers": {("kaadas", entry.entry_id)}, "name": settings.get("display_name") or nickname or "凯迪仕门锁", "manufacturer": "Kaadas"}
