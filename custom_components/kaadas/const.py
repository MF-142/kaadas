from __future__ import annotations

DOMAIN = "kaadas"

CONF_TOKEN = "token"
CONF_WIFI_SN = "wifi_sn"
CONF_UID = "uid"
CONF_POLL_INTERVAL_EVENT = "poll_interval_event"
CONF_POLL_INTERVAL_INFO = "poll_interval_info"
CONF_USER_AGENT = "user_agent"
CONF_PHONE_NAME = "phone_name"

API_BASE_URL = "https://app.kaadas.com:34000"
EVENT_ENDPOINT = "/app/record/operation/list"
DOORBELL_ENDPOINT = "/app/record/operation/visit"
DEVICE_INFO_ENDPOINT = "/app/user/findAllBindDevice"
ALARM_ENDPOINT = "/app/record/operation/alarm"

DEFAULT_INTERVALS = {"poll_interval_event": 5, "poll_interval_alarm": 5, "poll_interval_doorbell": 10, "poll_interval_info": 14400}
