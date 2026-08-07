from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import aiohttp
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from PIL import Image

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KaadasDoorbellImage(data["doorbell"], entry)])


class KaadasDoorbellImage(CoordinatorEntity, ImageEntity):
    """门铃抓拍图像实体。"""

    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        # 必须显式调用两个父类的 __init__，因为 CoordinatorEntity 不会自动向上传递
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self)
        self._entry = entry
        self._attr_name = "访客抓拍"
        self._attr_unique_id = f"{entry.entry_id}_doorbell_image"
        self._cached_image: bytes | None = None
        self._last_event_id: str | None = None
        self._image_last_updated: datetime | None = None

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

    @property
    def extra_state_attributes(self):
        """实体详情页显示的文字信息。"""
        data = self.coordinator.data
        return {
            "event_id": data.get("event_id"),
            "thumb_url": data.get("thumb_url"),
            "text_content": data.get("text_content"),
            "time": data.get("time"),
            "local_image": "/local/kaadas/doorbell_latest.jpg",
        }

    @property
    def image_last_updated(self) -> datetime | None:
        """HA 用此判断图片是否更新，前端会自动刷新。必须是 datetime 对象。"""
        return self._image_last_updated

    async def async_image(self) -> bytes | None:
        """下载、旋转并返回图片 bytes。"""
        event_id = self.coordinator.data.get("event_id")
        thumb_url = self.coordinator.data.get("thumb_url")

        if not thumb_url:
            return self._cached_image

        if event_id and event_id == self._last_event_id and self._cached_image:
            return self._cached_image

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(thumb_url, timeout=10) as response:
                    if response.status != 200:
                        _LOGGER.warning("下载门铃图片失败，状态码: %s", response.status)
                        return self._cached_image
                    image_bytes = await response.read()

            image = Image.open(io.BytesIO(image_bytes))
            rotated = image.rotate(90, expand=True)
            output = io.BytesIO()
            rotated.save(output, format=image.format or "JPEG")
            self._cached_image = output.getvalue()
            self._last_event_id = event_id
            self._image_last_updated = dt_util.utcnow()

            local_path = Path("/config/www/kaadas/doorbell_latest.jpg")
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(self._cached_image)

            return self._cached_image

        except Exception as err:
            _LOGGER.error("处理门铃图片出错: %s", err)
            return self._cached_image
