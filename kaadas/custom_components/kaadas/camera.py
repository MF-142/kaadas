from __future__ import annotations

import os
from pathlib import Path

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KaadasDoorbellCamera(data["doorbell"], entry, hass)])


class KaadasDoorbellCamera(Camera):
    def __init__(self, coordinator, entry: ConfigEntry, hass: HomeAssistant) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._entry = entry
        self._hass = hass

    @property
    def name(self) -> str:
        return "访客抓拍"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_doorbell_camera"

    @property
    def should_poll(self) -> bool:
        return False

    async def async_camera_image(self, image_width: int | None = None, image_height: int | None = None):
        url = self._coordinator.data.get("thumb_url")
        if not url:
            return None

        local_path = Path("/config/www/kaadas/doorbell_latest.jpg")
        local_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    return None
                image_bytes = await response.read()

        local_path.write_bytes(image_bytes)
        return image_bytes

    @property
    def entity_picture(self) -> str | None:
        if self._coordinator.last_update_success:
            return "/local/kaadas/doorbell_latest.jpg"
        return None
