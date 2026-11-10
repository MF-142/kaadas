"""Pure event interpretation; no network, credentials or HA dependencies."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math


def timestamp(value, tz=timezone.utc):
    """Return epoch seconds for seconds/ms/us or ISO/local datetime strings."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            return None
        while number >= 100_000_000_000:
            number /= 1000
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, OverflowError):
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
            return parsed.timestamp()
        except (ValueError, TypeError, OverflowError, OSError):
            return None


def lock_action(record):
    text = str(record.get("textContent") or "").strip()
    if text in ("门已上锁", "已上锁", "已锁定", "门已锁定", "门锁已锁定", "门锁已上锁"):
        return "locked"
    # A failure, instruction, attempt or alarm mentioning unlocking is not an unlock.
    if any(word in text for word in ("失败", "未开", "未解", "尝试", "请求", "错误", "禁止", "请", "未成功", "设置", "修改", "添加", "删除", "超时")):
        return None
    if ("报警" in text or "异常" in text) and "成功" not in text:
        return None
    if any(word in text for word in ("开锁", "解锁", "门锁打开", "门锁已打开")):
        return "unlocked"
    return None


def inside_match_name(settings=None):
    """Migrate the old numeric option to an explicit API nickname default."""
    settings = settings or {}
    if "inside_match_name" in settings:
        return str(settings["inside_match_name"]).strip()
    code = str(settings.get("inside_code", "106")).strip()
    return code if code.startswith("编号") else "编号" + code


def nickname_matches(record, match_name, mode="exact"):
    name = str(record.get("userNickname") or "").strip()
    match_name = str(match_name or "").strip()
    return bool(match_name) and (match_name in name if mode == "contains" else name == match_name)


def is_inside(record, settings=None):
    settings = settings or {}
    return nickname_matches(record, inside_match_name(settings), settings.get("inside_match_mode", "exact"))


def match_member(record, members, settings=None):
    if is_inside(record, settings):
        return None
    name = str(record.get("userNickname") or "").strip()
    # Identity is independent from whether a member's feedback entity is enabled.
    eligible = [m for m in members if m.get("match_name", "").strip()]
    exact = [m for m in eligible if nickname_matches(record, m["match_name"])]
    contains = [m for m in eligible if m.get("match_mode") == "contains" and nickname_matches(record, m["match_name"], "contains")]
    matches = exact or contains
    return sorted(matches, key=lambda m: (-len(m["match_name"]), m["id"]))[0] if matches else None


def record_key(record, parsed_time=None):
    identity = {"time": parsed_time if parsed_time is not None else timestamp(record.get("time"))}
    if record.get("eventId") is not None:
        identity["eventId"] = str(record["eventId"])
    else:
        identity.update({key: record.get(key) for key in ("textContent", "pwdNum", "userNickname")})
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class EventState:
    """Operation watermark, warning time comparison and cold-start baselines."""

    def __init__(self, saved=None, tz=timezone.utc):
        self.data = deepcopy(saved or {})
        self.data.setdefault("unlocked", None)
        self.data.pop("inside", None)  # v1.2.0 no longer has a separate inside sensor.
        self.data.setdefault("members", {})
        self.tz = tz
        self.alarm_ready = False

    def valid_records(self, records, now):
        valid = [(timestamp(r.get("time"), self.tz), r) for r in records if isinstance(r, dict)]
        return sorted([(t, r) for t, r in valid if t is not None and t <= now + 300], key=lambda x: x[0])

    def alarms(self, records, now):
        valid = self.valid_records(records, now)
        current = self.data.get("alarm")
        if not valid:
            return []
        time, latest = valid[-1]
        # Keep the complete warning text, without device identifiers from the body.
        latest = {key: latest.get(key) for key in ("time", "textContent", "textTitle", "type", "createTime")}
        self.data["alarm"] = {"watermark": time, "latest": latest}
        if not self.alarm_ready:
            self.alarm_ready = True
            return []
        if current is not None and time == current["watermark"]:
            return []
        return [{"type": "kaadas_alarm", "time": latest["time"], "text_content": latest.get("textContent"), "timestamp": time, "text_title": latest.get("textTitle"), "warning_type": latest.get("type"), "create_time": latest.get("createTime")}]

    def operations(self, records, members, now, settings=None):
        valid = self.valid_records(records, now)
        cursor = self.data.get("operation")
        first = cursor is None
        if not valid:
            if not records and first:
                self.data["operation"] = {"watermark": now, "keys": []}
            return []
        events = []
        watermark = cursor["watermark"] if cursor else 0
        keys = set(cursor.get("keys", [])) if cursor else set()
        for time, record in valid:
            key = record_key(record, time)
            if time < watermark or (time == watermark and key in keys):
                continue
            if time > watermark:
                watermark, keys = time, set()
            keys.add(key)
            action = lock_action(record)
            if action == "locked":
                self.data["unlocked"] = False
                for state in self.data["members"].values():
                    state["active"] = False
            elif action == "unlocked":
                self.data["unlocked"] = True
                inside = is_inside(record, settings)
                member = match_member(record, members, settings)
                source_type = "inside_handle" if inside else ("member" if member else "unknown")
                source_name = (settings or {}).get("inside_name", "内门把手") if inside else (member["name"] if member else "未知人员")
                self.data["last_unlock"] = {"time": record["time"], "source_type": source_type, "source_name": source_name, "member_id": member["id"] if member else None, "direction": "exit" if inside else ("entry" if member else "unknown")}
                if not first:
                    if member and member.get("feedback", True):
                        self.data["members"][member["id"]] = {"active": True, "last_time": record["time"]}
                        events.append({"type": "kaadas_member_return", "member_id": member["id"], "member_name": member["name"], "time": record["time"], "text_content": record.get("textContent"), "direction": "entry", "notify": member.get("notify", False)})
        self.data["operation"] = {"watermark": watermark, "keys": sorted(keys)}
        return events
