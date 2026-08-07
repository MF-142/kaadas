from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities = [
        KaadasLockEventSensor(data["lock_event"], entry),
        KaadasDoorbellSensor(data["doorbell"], entry),
        KaadasBatterySensor(data["device_info"], entry),
        KaadasWifiSensor(data["device_info"], entry),
        KaadasOpenCountSensor(data["device_info"], entry),
        KaadasLockNameSensor(data["device_info"], entry),
        KaadasAdminSensor(data["device_info"], entry),
    ]
    async_add_entities(entities)


class KaadasCoordinatorSensor(CoordinatorEntity):
    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "凯迪仕门锁",
            "manufacturer": "Kaadas",
        }


class KaadasLockEventSensor(KaadasCoordinatorSensor, SensorEntity):
    _attr_name = "上次开锁方式"
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_lock_event"

    @property
    def native_value(self):
        return self.coordinator.data.get("last_text_content")

    @property
    def extra_state_attributes(self):
        return {
            "time": self.coordinator.data.get("last_time"),
            "pwd_num": self.coordinator.data.get("last_pwd_num"),
            "pwd_nickname": self.coordinator.data.get("last_pwd_nickname"),
        }


class KaadasDoorbellSensor(KaadasCoordinatorSensor, SensorEntity):
    _attr_name = "门铃记录"
    _attr_icon = "mdi:doorbell"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_doorbell"

    @property
    def native_value(self):
        return self.coordinator.data.get("text_content")

    @property
    def extra_state_attributes(self):
        return {
            "time": self.coordinator.data.get("time"),
            "event_id": self.coordinator.data.get("event_id"),
            "thumb_url": self.coordinator.data.get("thumb_url"),
        }


class KaadasBatterySensor(KaadasCoordinatorSensor, SensorEntity):
    _attr_name = "电量"
    _attr_icon = "mdi:battery"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_battery"

    @property
    def native_value(self):
        return self.coordinator.data.get("power")


class KaadasWifiSensor(KaadasCoordinatorSensor, SensorEntity):
    _attr_name = "WiFi名称"
    _attr_icon = "mdi:wifi"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_wifi"

    @property
    def native_value(self):
        return self.coordinator.data.get("wifi_name")


class KaadasOpenCountSensor(KaadasCoordinatorSensor, SensorEntity):
    _attr_name = "开锁计数"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_open_count"

    @property
    def native_value(self):
        return self.coordinator.data.get("open_count")


class KaadasLockNameSensor(KaadasCoordinatorSensor, SensorEntity):
    _attr_name = "门锁名称"
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_lock_name"

    @property
    def native_value(self):
        return self.coordinator.data.get("lock_nickname")


class KaadasAdminSensor(KaadasCoordinatorSensor, SensorEntity):
    _attr_name = "管理员"
    _attr_icon = "mdi:account"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_admin"

    @property
    def native_value(self):
        return self.coordinator.data.get("admin_name")
