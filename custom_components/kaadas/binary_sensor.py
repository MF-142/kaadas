from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["lock_event"]
    entities = [
        KaadasUserBinarySensor(coordinator, entry, index)
        for index in range(1, 5)
    ]
    async_add_entities(entities)


class KaadasUserBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry: ConfigEntry, user_index: int) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._user_index = user_index

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_user_{self._user_index}"

    @property
    def name(self) -> str:
        return f"用户{self._user_index}状态"

    @property
    def is_on(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        pwd_num = self.coordinator.data.get("last_pwd_num")
        text_content = self.coordinator.data.get("last_text_content")
        if text_content == "门已上锁":
            return False
        return str(pwd_num) == str(self._user_index - 1)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "凯迪仕门锁",
            "manufacturer": "Kaadas",
        }
