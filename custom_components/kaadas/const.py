from __future__ import annotations

DOMAIN = "kaadas"

CONF_TOKEN = "token"
CONF_WIFI_SN = "wifi_sn"
CONF_UID = "uid"
CONF_POLL_INTERVAL_EVENT = "poll_interval_event"
CONF_POLL_INTERVAL_INFO = "poll_interval_info"

DEFAULT_EVENT_POLL = 10
DEFAULT_INFO_POLL = 3600

API_BASE_URL = "https://app.kaadas.com:34000"
EVENT_ENDPOINT = "/app/record/operation/list"
DOORBELL_ENDPOINT = "/app/record/operation/visit"
DEVICE_INFO_ENDPOINT = "/app/user/findAllBindDevice"

DEFAULT_HEADERS = {
    "Host": "app.kaadas.com:34000",
    "reqSource": "app",
    "phoneName": "iPhone 7 Plus",
    "lang": "zh_CN",
    "User-Agent": "KaadasLock/6.14.3 (iPhone; iOS 15.8.8; Scale/3.00)",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
}
