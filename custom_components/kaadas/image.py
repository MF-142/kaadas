from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KaadasDoorbellImage(data["doorbell"], entry)])


class KaadasDoorbellImage(ImageEntity):
    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._entry = entry
        self._attr_name = "访客抓拍"
        self._attr_unique_id = f"{entry.entry_id}_doorbell_image"

    @property
    def image_url(self) -> str | None:
        if self.coordinator.last_update_success:
            return "/local/kaadas/doorbell_latest.jpg"
        return None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "凯迪仕门锁",
            "manufacturer": "Kaadas",
        }
