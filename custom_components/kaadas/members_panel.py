"""Dedicated, administrator-only horizontal editor for existing member options.

This module changes only the UI/CRUD transport. Business runtime, API and stored
member shape are preserved. No token or account details are sent to the panel.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .state import is_inside

PANEL_PATH = "kaadas-members"
STATIC_PATH = "/kaadas-members-static"
MEMBER_FIELDS = ("id", "name", "match_name", "match_mode", "feedback", "notify")
_REGISTERED = "kaadas_members_panel_registered"


def _revision(members: list[dict]) -> str:
    """Concurrency guard for updates from other options screens."""
    encoded = json.dumps(members, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _get_entry(hass: HomeAssistant, entry_id: str):
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    return entry


def _entry_public(entry) -> dict:
    """Never expose credentials or other unrelated settings over the websocket."""
    members = entry.options.get("members", entry.data.get("members", []))
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "members": [
            {field: member.get(field) for field in MEMBER_FIELDS}
            for member in members
        ],
        "revision": _revision(members),
    }


def _validated_members(items: list[dict], old: list[dict], settings: dict) -> list[dict]:
    old_by_id = {str(member["id"]): member for member in old}
    new_members = []
    used_ids = set()
    used_match_names = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("成员行的格式不正确")
        name = str(item.get("name") or "").strip()
        match_name = str(item.get("match_name") or "").strip()
        mode = str(item.get("match_mode") or "exact")
        if not name or not match_name:
            raise ValueError("请填写每位成员的显示名称和接口昵称")
        if len(name) > 100 or len(match_name) > 100:
            raise ValueError("成员名称不能超过100个字符")
        if mode not in ("exact", "contains"):
            raise ValueError("匹配方式只能选择精准匹配或包含匹配")
        if match_name in used_match_names:
            raise ValueError("接口昵称不能重复，请检查重复的成员")
        if is_inside({"userNickname": match_name}, settings):
            raise ValueError("接口昵称与内门把手匹配设置冲突")
        used_match_names.add(match_name)

        requested_id = str(item.get("id") or "")
        if requested_id.startswith("tmp:") or not requested_id:
            member_id = uuid4().hex
            base = {}
        elif requested_id in old_by_id:
            member_id = requested_id
            base = deepcopy(old_by_id[requested_id])
        else:
            raise ValueError("成员标识已改变，请刷新页面后重试")
        if member_id in used_ids:
            raise ValueError("成员标识重复")
        used_ids.add(member_id)
        feedback = item.get("feedback", True)
        notify = item.get("notify", False)
        if not isinstance(feedback, bool) or not isinstance(notify, bool):
            raise ValueError("开门反馈和通知必须使用勾选状态")
        base.update({
            "id": member_id,
            "name": name,
            "match_name": match_name,
            "match_mode": mode,
            "feedback": feedback,
            "notify": notify if feedback else False,
        })
        new_members.append(base)
    return new_members


def _require_admin(connection, message_id):
    if not connection.user.is_admin:
        connection.send_error(message_id, "unauthorized", "只有HA管理员可以编辑成员")
        return False
    return True


@websocket_api.websocket_command({vol.Required("type"): "kaadas/members/get"})
@callback
def ws_get_members(hass, connection, msg):
    if not _require_admin(connection, msg["id"]):
        return
    entries = [
        _entry_public(entry) for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "kaadas/members/save",
        vol.Required("entry_id"): str,
        vol.Required("revision"): str,
        vol.Required("members"): vol.All([dict], vol.Length(max=500)),
    }
)
@callback
def ws_save_members(hass, connection, msg):
    if not _require_admin(connection, msg["id"]):
        return
    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "找不到对应的凯迪仕门锁配置")
        return
    old = entry.options.get("members", entry.data.get("members", []))
    if msg["revision"] != _revision(old):
        connection.send_error(msg["id"], "conflict", "成员设置已在其他窗口修改，请刷新后重试")
        return
    try:
        new_members = _validated_members(msg["members"], old, {**entry.data, **entry.options})
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_members", str(err))
        return
    # Preserve every other option and the full data (token, UID, api headers etc.).
    # The existing update listener reloads the entry to apply member changes.
    if new_members != old:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, "members": new_members},
        )
    connection.send_result(msg["id"], _entry_public(entry))


async def async_register_members_panel(hass: HomeAssistant) -> None:
    """Register a URL-only (no sidebar) HA panel plus authenticated commands."""
    if hass.data.get(_REGISTERED):
        return
    directory = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_PATH, str(directory), cache_headers=False)]
    )
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="kaadas-members-panel",
        frontend_url_path=PANEL_PATH,
        sidebar_title=None,
        sidebar_icon="mdi:account-group",
        module_url=f"{STATIC_PATH}/members-panel.js?v=1.3.4",
        require_admin=True,
    )
    websocket_api.async_register_command(hass, ws_get_members)
    websocket_api.async_register_command(hass, ws_save_members)
    hass.data[_REGISTERED] = True
