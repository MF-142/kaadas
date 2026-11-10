"""Lock and independent member feedback; never infer physical door contact."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .runtime import device_info


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["lock_event"]
    members = {**entry.data, **entry.options}.get("members", [])
    entities = [KaadasStateSensor(coordinator, entry, "overall", "门锁总体状态")]
    entities.extend(KaadasStateSensor(coordinator, entry, "member_" + m["id"], m["name"] + " 开门反馈", m) for m in members if m.get("feedback", True))
    async_add_entities(entities)


class KaadasStateSensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, key, name, member=None):
        super().__init__(coordinator)
        self._entry, self.key, self.member = entry, key, member
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        if key == "overall":
            self._attr_device_class = BinarySensorDeviceClass.LOCK
        else:
            self._attr_icon = "mdi:account-key" if member else "mdi:door-open"

    @property
    def device_info(self):
        return device_info(self.hass, self._entry)

    @property
    def is_on(self):
        state = self.coordinator.state.engine.data
        if self.key == "overall":
            return state["unlocked"]
        return state["members"].get(self.member["id"], {}).get("active", False)

    @property
    def extra_state_attributes(self):
        if self.member:
            return {"member_id": self.member["id"], "last_time": self.coordinator.state.engine.data["members"].get(self.member["id"], {}).get("last_time"), "meaning": "开门反馈，不代表在家或离家"}
        last = self.coordinator.state.engine.data.get("last_unlock", {})
        settings = {**self._entry.data, **self._entry.options}
        name = last.get("source_name")
        if last.get("source_type") == "inside_handle":
            name = settings.get("inside_name", "内门把手")
        elif last.get("member_id"):
            member = next((m for m in settings.get("members", []) if m["id"] == last["member_id"]), None)
            if member:
                name = member["name"]
        return {"meaning": "on=已开锁，off=已锁定；来源/方向仅描述最近开锁", "last_unlock_time": last.get("time"), "last_unlock_source": name, "last_unlock_source_type": last.get("source_type"), "last_unlock_member_id": last.get("member_id"), "last_unlock_direction": last.get("direction")}
