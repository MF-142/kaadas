from __future__ import annotations

import io
import logging
from pathlib import Path

import aiohttp
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from PIL import Image

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        self._cached_image: bytes | None = None
        self._last_event_id: str | None = None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "凯迪仕门锁",
            "manufacturer": "Kaadas",
        }

    async def async_image(self) -> bytes | None:
        """下载、旋转并返回图片 bytes。HA 每次查看图片时调用。"""
        event_id = self.coordinator.data.get("event_id")
        thumb_url = self.coordinator.data.get("thumb_url")

        if not thumb_url:
            return self._cached_image

        # 同一个事件直接返回缓存，避免重复下载/旋转
        if event_id and event_id == self._last_event_id and self._cached_image:
            return self._cached_image

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(thumb_url, timeout=10) as response:
                    if response.status != 200:
                        _LOGGER.warning("下载门铃图片失败，状态码: %s", response.status)
                        return self._cached_image
                    image_bytes = await response.read()

            # 逆时针旋转 90 度
            image = Image.open(io.BytesIO(image_bytes))
            rotated = image.rotate(90, expand=True)
            output = io.BytesIO()
            rotated.save(output, format=image.format or "JPEG")
            self._cached_image = output.getvalue()
            self._last_event_id = event_id

            # 同时保存到本地，供 sensor 的 local_image 引用
            local_path = Path("/config/www/kaadas/doorbell_latest.jpg")
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(self._cached_image)

            return self._cached_image

        except Exception as err:
            _LOGGER.error("处理门铃图片出错: %s", err)
            return self._cached_image
