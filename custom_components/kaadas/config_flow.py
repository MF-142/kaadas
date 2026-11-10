"""Connection settings and stable-ID member CRUD through HA options."""
from copy import deepcopy
from uuid import uuid4
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
from .const import DOMAIN, DEFAULT_INTERVALS
from .api import HEADER_FIELDS
from .state import is_inside, inside_match_name
from .login_client import (
    KaadasClient,
    ProtocolError,
    DEFAULT_PHONE_NAME,
    DEFAULT_UA,
    DEFAULT_APP_VERSION,
    DEFAULT_OS_VERSION,
)
from . import put_captcha, remove_captcha


# ---------- UI labels: use direct Chinese labels to avoid frontend translation cache issues ----------
AUTO_ACCOUNT = "凯迪仕智能 App 登录账号（通常为手机号）"
AUTO_PASSWORD = "凯迪仕智能 App 登录密码"
AUTO_USE_CAPTCHA = "使用图形验证码登录（仅在需要时勾选）"
AUTO_NORMAL_MODE = "普通登录时账号格式"
AUTO_CAPTCHA_MODE = "图形验证码登录时账号格式"
AUTO_APP_VERSION = "凯迪仕 App 版本 appVersion"
AUTO_CAPTCHA_CODE = "图形验证码"
AUTO_CAPTCHA_REFRESH = "重新获取验证码（勾选后提交）"
AUTO_DEVICE = "请选择要接入 Home Assistant 的凯迪仕门锁"
AUTO_DEVICE_NAME = "HA 门锁显示名称（留空使用门锁昵称）"
AUTO_RETRY = "重新查询绑定门锁列表"
AUTO_WIFI_SN = "门锁序列号 wifiSN"

MANUAL_TOKEN = "访问令牌 Token（从抓包请求头获取）"
MANUAL_WIFI_SN = "门锁序列号 wifiSN（从抓包数据或绑定设备信息获取）"
MANUAL_UID = "用户 UID（从登录响应获取）"
MANUAL_USER_AGENT = "客户端标识 User-Agent（从抓包请求头获取）"
MANUAL_PHONE_NAME = "设备名称 phoneName（从抓包请求头获取）"
MANUAL_DISPLAY_NAME = "HA 门锁显示名称（留空使用门锁昵称）"

CONN_MODE = "请选择更新方式"
CONN_MODE_AUTO = "① 自动登录：使用 App 账号密码重新获取 Token / UID / 设备信息"
CONN_MODE_MANUAL = "② 手动登录：手动填写最新抓包参数"

MEMBER_NAME = "HA 显示名称（仅用于展示）"
MEMBER_MATCH_NAME = "接口昵称（填写实际抓取值）"
MEMBER_MATCH_MODE = "匹配方式"
MEMBER_FEEDBACK = "启用成员开门反馈"
MEMBER_NOTIFY = "显示此成员的 HA 通知"
MEMBER_ACTION = "成员操作（保存状态／添加／编辑／删除）"

MATCH_MODE_OPTIONS = {"exact": "精准匹配", "contains": "包含匹配"}
NORMAL_MODE_OPTIONS = {
    "as_entered": "原样使用输入的账号（默认）",
    "auto86": "11位大陆手机号自动补86",
}
CAPTCHA_MODE_OPTIONS = {
    "auto86": "11位大陆手机号自动补86（默认）",
    "as_entered": "原样使用输入的账号",
}


def text_field(password: bool = False):
    return selector.TextSelector(
        selector.TextSelectorConfig(
            type=selector.TextSelectorType.PASSWORD if password else selector.TextSelectorType.TEXT
        )
    )


def connection_schema(settings, initial=False):
    fields = {
        vol.Required(MANUAL_TOKEN, default=settings.get("token", "")): text_field(True),
        vol.Required(MANUAL_UID, default=settings.get("uid", "")): str,
        vol.Required(MANUAL_USER_AGENT, default=settings.get("user_agent", "")): str,
        vol.Required(MANUAL_PHONE_NAME, default=settings.get("phone_name", "")): str,
    }
    if initial:
        fields[vol.Required(MANUAL_WIFI_SN, default=settings.get("wifi_sn", ""))] = str
    fields[vol.Optional(MANUAL_DISPLAY_NAME, default=settings.get("display_name", ""))] = str
    return vol.Schema(fields)


def normalize_manual_input(user_input: dict) -> dict:
    return {
        "token": str(user_input.get(MANUAL_TOKEN, "")).strip(),
        "uid": str(user_input.get(MANUAL_UID, "")).strip(),
        "user_agent": str(user_input.get(MANUAL_USER_AGENT, "")).strip(),
        "phone_name": str(user_input.get(MANUAL_PHONE_NAME, "")).strip(),
        "wifi_sn": str(user_input.get(MANUAL_WIFI_SN, "")).strip(),
        "display_name": str(user_input.get(MANUAL_DISPLAY_NAME, "")).strip(),
    }


def auto_schema(defaults=None):
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(AUTO_ACCOUNT, default=values.get("account", "")): str,
            vol.Required(AUTO_PASSWORD, default=values.get("password", "")): text_field(password=True),
            vol.Optional(AUTO_USE_CAPTCHA, default=values.get("use_captcha", False)): bool,
            vol.Optional(AUTO_NORMAL_MODE, default=values.get("normal_account_mode", "as_entered")): vol.In(NORMAL_MODE_OPTIONS),
            vol.Optional(AUTO_CAPTCHA_MODE, default=values.get("captcha_account_mode", "auto86")): vol.In(CAPTCHA_MODE_OPTIONS),
            vol.Optional(AUTO_APP_VERSION, default=values.get("app_version", DEFAULT_APP_VERSION)): str,
            # 具体设备型号、系统版本和设备标识不向配置界面暴露。
        }
    )


def normalize_auto_input(user_input: dict) -> dict:
    return {
        "account": str(user_input.get(AUTO_ACCOUNT, "")).strip(),
        "password": str(user_input.get(AUTO_PASSWORD, "")),
        "use_captcha": bool(user_input.get(AUTO_USE_CAPTCHA, False)),
        "normal_account_mode": user_input.get(AUTO_NORMAL_MODE, "as_entered"),
        "captcha_account_mode": user_input.get(AUTO_CAPTCHA_MODE, "auto86"),
        "app_version": str(user_input.get(AUTO_APP_VERSION, DEFAULT_APP_VERSION)).strip(),
    }


class LoginFlowMixin:
    def _init_login_state(self):
        self._login_client: KaadasClient | None = None
        self._devices: list[dict] = []
        self._captcha_url: str | None = None
        self._login_result = "尚未登录"
        self._device_warning = ""
        self._chosen: dict | None = None
        self._selected_display_name: str = ""
        self._auto_defaults: dict = {}

    async def _close_login(self) -> None:
        if self._captcha_url:
            remove_captcha(self.hass, self._captcha_url)
            self._captcha_url = None
        if self._login_client is not None:
            await self._login_client.close()
            self._login_client = None

    async def _start_auto_login(self, auto_input: dict):
        await self._close_login()
        self._auto_defaults = {**self._auto_defaults, **auto_input, "password": ""}
        account = auto_input["account"]
        password = auto_input["password"]
        self._login_client = KaadasClient(
            account=account,
            password=password,
            normal_account_mode=auto_input.get("normal_account_mode", "as_entered"),
            captcha_account_mode=auto_input.get("captcha_account_mode", "auto86"),
            padding_mode="PKCS1v15",
            phone_name=DEFAULT_PHONE_NAME,
            user_agent=DEFAULT_UA,
            app_version=auto_input.get("app_version", DEFAULT_APP_VERSION),
            os_version=DEFAULT_OS_VERSION,
            unique_code=None,
            device_user_agent=None,
            device_phone_name=None,
        )
        await self._login_client.fetch_public_key()
        if auto_input.get("use_captcha", False):
            return False, True
        outcome = await self._login_client.login_normal()
        if outcome.ok:
            return True, False
        if outcome.challenge_needed:
            self._login_result = f"服务器要求图形验证码：业务码 {outcome.code}，{outcome.message}。"
            return False, True
        self._login_result = f"业务码 {outcome.code}：{outcome.message}。如 App 需要图形验证码，可勾选后重试。"
        await self._close_login()
        return False, False

    async def _fetch_captcha_form(self, step_id: str, user_input=None, errors=None):
        errors = errors or {}
        if self._captcha_url is None or (user_input is not None and user_input.get(AUTO_CAPTCHA_REFRESH, False)):
            try:
                image = await self._login_client.fetch_captcha()
                if self._captcha_url:
                    remove_captcha(self.hass, self._captcha_url)
                self._captcha_url = put_captcha(self.hass, image)
            except ProtocolError:
                errors["base"] = "cannot_fetch_captcha"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Optional(AUTO_CAPTCHA_CODE, default=""): str,
                vol.Optional(AUTO_CAPTCHA_REFRESH, default=False): bool,
            }),
            errors=errors,
            description_placeholders={
                "captcha_url": self._captcha_url or "#",
                "login_result": self._login_result,
            },
        )

    async def _load_devices_after_login(self):
        if self._login_client is None:
            raise ProtocolError("login client not ready")
        try:
            self._devices = await self._login_client.fetch_devices()
            self._device_warning = "无"
        except ProtocolError:
            self._devices = []
            self._device_warning = "登录成功，但自动查询绑定设备失败。可返回重试，不会将未知设备号写入配置。"

    def _device_schema(self):
        choices = {
            str(i): f"{str(d.get('lockNickname') or d.get('productModel') or '门锁')[:60]}（设备序列号尾号：{str(d.get('wifiSN') or '')[-4:] or '未知'}）"
            for i, d in enumerate(self._devices)
        }
        fields = {}
        if choices:
            fields[vol.Required(AUTO_DEVICE, default=next(iter(choices)))] = vol.In(choices)
        fields[vol.Optional(AUTO_DEVICE_NAME, default=self._selected_display_name)] = str
        fields[vol.Optional(AUTO_RETRY, default=False)] = bool
        return vol.Schema(fields), choices


class KaadasConfigFlow(LoginFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """在原版 V1.2.2 的手动配置前增加两种登录模式选择。"""

    VERSION = 1

    def __init__(self) -> None:
        self._init_login_state()

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            if user_input["login_mode"] == "auto":
                return await self.async_step_auto()
            return await self.async_step_manual()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("login_mode", default="auto"): vol.In({
                    "auto": "① 自动登录：App 账号、密码，自动提取门锁信息",
                    "manual": "② 手动登录：输入抓包取得的五项参数",
                })}
            ),
        )

    async def async_step_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            values = normalize_manual_input(user_input)
            if all(values.get(k) for k in ("token", "uid", "wifi_sn", "user_agent", "phone_name")):
                await self.async_set_unique_id(values["wifi_sn"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=values.get("display_name") or "凯迪仕门锁",
                    data={**DEFAULT_INTERVALS, **values, "login_mode": "manual"},
                )
            errors["base"] = "required_value"
        # 手动模式由使用者填写当前会话中的请求头，不预填具体设备型号。
        return self.async_show_form(step_id="manual", data_schema=connection_schema(user_input or {}, True), errors=errors)

    async def async_step_auto(self, user_input=None):
        errors = {}
        if user_input is not None:
            auto_input = normalize_auto_input(user_input)
            if not auto_input["account"] or not auto_input["password"]:
                errors["base"] = "required_value"
            else:
                try:
                    ok, need_captcha = await self._start_auto_login(auto_input)
                    if ok:
                        await self._load_devices_after_login()
                        return await self.async_step_device()
                    if need_captcha:
                        return await self.async_step_captcha()
                    errors["base"] = "invalid_auth"
                except ProtocolError:
                    errors["base"] = "cannot_connect"
                    self._login_result = "连接或响应格式异常，请检查网络及认证参数。"
                    await self._close_login()
        defaults = self._auto_defaults or {
            "normal_account_mode": "as_entered",
            "captcha_account_mode": "auto86",
            "app_version": DEFAULT_APP_VERSION,
            "use_captcha": False,
        }
        return self.async_show_form(
            step_id="auto",
            data_schema=auto_schema(defaults),
            errors=errors,
            description_placeholders={"login_result": self._login_result},
        )

    async def async_step_captcha(self, user_input=None):
        if self._login_client is None:
            return await self.async_step_auto()
        errors = {}
        if user_input is not None and not user_input.get(AUTO_CAPTCHA_REFRESH, False):
            code = str(user_input.get(AUTO_CAPTCHA_CODE) or "").strip()
            if not code:
                errors["base"] = "missing_captcha"
            else:
                try:
                    result = await self._login_client.login_abnormal(code)
                    if result.ok:
                        await self._load_devices_after_login()
                        return await self.async_step_device()
                    errors["base"] = "invalid_captcha_or_auth"
                    self._login_result = f"验证业务码 {result.code}：{result.message}。可刷新验证码再试。"
                except ProtocolError:
                    errors["base"] = "cannot_connect"
        return await self._fetch_captcha_form("captcha", user_input, errors)

    async def async_step_device(self, user_input=None):
        if self._login_client is None or not self._login_client.token or not self._login_client.uid:
            return await self.async_step_auto()
        errors = {}
        if user_input is not None and user_input.get(AUTO_RETRY, False):
            await self._load_devices_after_login()
        schema, choices = self._device_schema()
        if user_input is not None and not user_input.get(AUTO_RETRY, False):
            index = str(user_input.get(AUTO_DEVICE) or "")
            if index not in choices:
                errors["base"] = "select_device"
            else:
                self._chosen = self._devices[int(index)]
                self._selected_display_name = str(user_input.get(AUTO_DEVICE_NAME) or "").strip()
                if not str(self._chosen.get("wifiSN") or "").strip():
                    return await self.async_step_missing_sn()
                return await self._create_auto_entry(self._chosen["wifiSN"])
        return self.async_show_form(
            step_id="device",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(self._devices)), "warning": self._device_warning or "无"},
        )

    async def async_step_missing_sn(self, user_input=None):
        if self._login_client is None or self._chosen is None:
            return await self.async_step_auto()
        errors = {}
        if user_input is not None:
            wifi_sn = str(user_input.get(AUTO_WIFI_SN) or "").strip()
            if wifi_sn:
                return await self._create_auto_entry(wifi_sn)
            errors["base"] = "required_value"
        return self.async_show_form(step_id="missing_sn", data_schema=vol.Schema({vol.Required(AUTO_WIFI_SN): str}), errors=errors)

    async def _create_auto_entry(self, wifi_sn: str):
        client = self._login_client
        if client is None or not client.token or not client.uid:
            return await self.async_step_auto()
        await self.async_set_unique_id(str(wifi_sn).strip())
        self._abort_if_unique_id_configured()
        chosen = self._chosen or {}
        display_name = self._selected_display_name or str(chosen.get("lockNickname") or "").strip()
        data = {
            **DEFAULT_INTERVALS,
            "token": client.token,
            "uid": client.uid,
            "wifi_sn": str(wifi_sn).strip(),
            "user_agent": client.device_user_agent,
            "phone_name": client.device_phone_name,
            "display_name": display_name,
            "login_mode": "auto",
        }
        await self._close_login()
        return self.async_create_entry(title=display_name or "凯迪仕门锁", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return KaadasOptionsFlowHandler(config_entry)


class KaadasOptionsFlowHandler(LoginFlowMixin, config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._entry = config_entry
        self.settings = deepcopy({**config_entry.data, **config_entry.options})
        self.edit_id = None
        self.endpoint = "alarm"
        self._init_login_state()
        self._auto_defaults = {
            "normal_account_mode": "as_entered",
            "captcha_account_mode": "auto86",
            "app_version": DEFAULT_APP_VERSION,
            "use_captcha": False,
        }

    def save(self):
        return self.async_create_entry(title="", data=self.settings)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "connection": "连接与显示名称",
                "polling": "轮询与预警通知",
                "headers": "独立接口请求头",
                "inside_handle": "内门把手配置",
                "members": "成员管理（横向表格、添加、删除）",
            },
        )

    async def async_step_connection(self, user_input=None):
        if user_input is not None:
            if user_input.get(CONN_MODE) == CONN_MODE_AUTO:
                return await self.async_step_connection_auto()
            return await self.async_step_connection_manual()
        return self.async_show_form(
            step_id="connection",
            data_schema=vol.Schema({vol.Required(CONN_MODE, default=CONN_MODE_AUTO): vol.In([CONN_MODE_AUTO, CONN_MODE_MANUAL])}),
        )

    async def async_step_connection_manual(self, user_input=None):
        errors = {}
        if user_input is not None:
            values = normalize_manual_input(user_input)
            if all(values.get(k) for k in ("token", "uid", "user_agent", "phone_name")):
                self.settings.update({k: v for k, v in values.items() if v or k == "display_name"})
                self.settings["login_mode"] = "manual"
                return self.save()
            errors["base"] = "required_value"
        defaults = {**self.settings}
        return self.async_show_form(step_id="connection_manual", data_schema=connection_schema(defaults), errors=errors)

    async def async_step_connection_auto(self, user_input=None):
        errors = {}
        if user_input is not None:
            auto_input = normalize_auto_input(user_input)
            if not auto_input["account"] or not auto_input["password"]:
                errors["base"] = "required_value"
            else:
                try:
                    ok, need_captcha = await self._start_auto_login(auto_input)
                    if ok:
                        await self._load_devices_after_login()
                        return await self.async_step_connection_device()
                    if need_captcha:
                        return await self.async_step_connection_captcha()
                    errors["base"] = "invalid_auth"
                except ProtocolError:
                    errors["base"] = "cannot_connect"
                    self._login_result = "连接或响应格式异常，请检查网络及认证参数。"
                    await self._close_login()
        return self.async_show_form(
            step_id="connection_auto",
            data_schema=auto_schema(self._auto_defaults),
            errors=errors,
            description_placeholders={"login_result": self._login_result},
        )

    async def async_step_connection_captcha(self, user_input=None):
        if self._login_client is None:
            return await self.async_step_connection_auto()
        errors = {}
        if user_input is not None and not user_input.get(AUTO_CAPTCHA_REFRESH, False):
            code = str(user_input.get(AUTO_CAPTCHA_CODE) or "").strip()
            if not code:
                errors["base"] = "missing_captcha"
            else:
                try:
                    result = await self._login_client.login_abnormal(code)
                    if result.ok:
                        await self._load_devices_after_login()
                        return await self.async_step_connection_device()
                    errors["base"] = "invalid_captcha_or_auth"
                    self._login_result = f"验证业务码 {result.code}：{result.message}。可刷新验证码再试。"
                except ProtocolError:
                    errors["base"] = "cannot_connect"
        return await self._fetch_captcha_form("connection_captcha", user_input, errors)

    async def async_step_connection_device(self, user_input=None):
        if self._login_client is None or not self._login_client.token or not self._login_client.uid:
            return await self.async_step_connection_auto()
        errors = {}
        if user_input is not None and user_input.get(AUTO_RETRY, False):
            await self._load_devices_after_login()
        schema, choices = self._device_schema()
        if user_input is not None and not user_input.get(AUTO_RETRY, False):
            index = str(user_input.get(AUTO_DEVICE) or "")
            if index not in choices:
                errors["base"] = "select_device"
            else:
                self._chosen = self._devices[int(index)]
                self._selected_display_name = str(user_input.get(AUTO_DEVICE_NAME) or "").strip()
                if not str(self._chosen.get("wifiSN") or "").strip():
                    return await self.async_step_connection_missing_sn()
                return await self._save_auto_connection(self._chosen["wifiSN"])
        return self.async_show_form(
            step_id="connection_device",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(self._devices)), "warning": self._device_warning or "无"},
        )

    async def async_step_connection_missing_sn(self, user_input=None):
        if self._login_client is None or self._chosen is None:
            return await self.async_step_connection_auto()
        errors = {}
        if user_input is not None:
            wifi_sn = str(user_input.get(AUTO_WIFI_SN) or "").strip()
            if wifi_sn:
                return await self._save_auto_connection(wifi_sn)
            errors["base"] = "required_value"
        return self.async_show_form(step_id="connection_missing_sn", data_schema=vol.Schema({vol.Required(AUTO_WIFI_SN): str}), errors=errors)

    async def _save_auto_connection(self, wifi_sn: str):
        client = self._login_client
        if client is None or not client.token or not client.uid:
            return await self.async_step_connection_auto()
        # Reauthentication/credential update must never silently switch a config entry
        # to another lock: entry unique_id, entity registry and member feedback belong
        # to the original wifiSN. A different device requires a new config entry.
        existing_sn = str(self.settings.get("wifi_sn") or "").strip()
        if existing_sn and str(wifi_sn).strip() != existing_sn:
            self._device_warning = "选中的门锁不是当前集成绑定的门锁，请重新选择同一设备；新增另一把门锁请使用‘添加集成’。"
            return await self.async_step_connection_device()
        chosen = self._chosen or {}
        display_name = self._selected_display_name or str(chosen.get("lockNickname") or self.settings.get("display_name") or "").strip()
        self.settings.update(
            {
                "token": client.token,
                "uid": client.uid,
                "wifi_sn": str(wifi_sn).strip(),
                "user_agent": client.device_user_agent,
                "phone_name": client.device_phone_name,
                "display_name": display_name,
                "login_mode": "auto",
            }
        )
        await self._close_login()
        return self.save()

    async def async_step_inside_handle(self, user_input=None):
        errors = {}
        if user_input is not None:
            values = {key: value.strip() for key, value in user_input.items()}
            if not values.get("inside_match_name") or not values.get("inside_name"):
                errors["base"] = "required_value"
            elif any(is_inside({"userNickname": m["match_name"]}, values) for m in self.settings.get("members", [])):
                errors["base"] = "inside_conflict"
            else:
                self.settings.update(values)
                self.settings.pop("inside_code", None)
                return self.save()
        values = user_input or self.settings
        schema = vol.Schema({
            vol.Required("inside_match_name", default=inside_match_name(values)): str,
            vol.Required("inside_match_mode", default=values.get("inside_match_mode", "exact")): vol.In(MATCH_MODE_OPTIONS),
            vol.Required("inside_name", default=values.get("inside_name", "内门把手")): str,
        })
        return self.async_show_form(step_id="inside_handle", data_schema=schema, errors=errors)

    async def async_step_polling(self, user_input=None):
        errors = {}
        if user_input is not None:
            if dt_util.get_time_zone(user_input["event_timezone"]) is None:
                errors["base"] = "invalid_timezone"
            else:
                self.settings.update(user_input)
                return self.save()
        fields = {vol.Required(k, default=self.settings.get(k, v)): vol.All(vol.Coerce(int), vol.Range(min=1, max=86400)) for k, v in DEFAULT_INTERVALS.items()}
        fields[vol.Required("event_timezone", default=self.settings.get("event_timezone", "Asia/Shanghai"))] = str
        fields[vol.Required("alarm_notify", default=self.settings.get("alarm_notify", True))] = bool
        return self.async_show_form(step_id="polling", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_headers(self, user_input=None):
        if user_input is not None:
            self.endpoint = user_input["endpoint"]
            return await self.async_step_header_values()
        return self.async_show_form(step_id="headers", data_schema=vol.Schema({vol.Required("endpoint", default="alarm"): vol.In({"event": "开锁记录", "alarm": "异常事件", "doorbell": "门铃访客", "info": "设备信息"})}))

    async def async_step_header_values(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input = dict(user_input)
            if any("\r" in v or "\n" in v for v in user_input.values()):
                errors["base"] = "invalid_header"
            else:
                if self.endpoint == "alarm":
                    self.settings["alarm_ver"] = user_input.pop("alarm_ver")
                self.settings.setdefault("headers", {})[self.endpoint] = user_input
                return self.save()
        values = self.settings.get("headers", {}).get(self.endpoint, {})
        fields = {vol.Optional(k, default=values.get(k, "")): text_field(k == "token") for k in HEADER_FIELDS}
        if self.endpoint == "alarm":
            fields[vol.Required("alarm_ver", default=self.settings.get("alarm_ver", "20231127"))] = vol.Match(r"^\d{8}$")
        return self.async_show_form(step_id="header_values", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_members(self, user_input=None):
        """Offer visible navigation choices instead of an empty options form.

        Home Assistant 2026.11 can render a vol.Schema({}) step with no
        description or link, leaving the member management window blank.
        A native HA menu always presents explicit actionable choices.
        Neither navigation choice saves or modifies entry configuration.
        """
        return self.async_show_menu(
            step_id="members",
            menu_options={
                "open_members_editor": "打开横向成员管理表格",
                "members_link": "查看或复制成员管理地址（备用）",
            },
        )

    async def async_step_open_members_editor(self, user_input=None):
        """Show a real link to the local panel, not an OAuth external step.

        `async_external_step` requires an external callback/flow completion.
        A standalone Home Assistant panel has no such callback and an
        EXTERNAL_STEP result leaves the options dialog blank/stalled.
        Present a nonempty native form with an in-app URL instead.
        """
        if user_input is not None:
            # Submission is not a save action. Return to the menu; actual
            # member changes are saved only in the dedicated table.
            return await self.async_step_members()

        import logging
        panel_status = "已注册"
        if not self.hass.data.get("kaadas_members_panel_registered"):
            try:
                from .members_panel import async_register_members_panel
                await async_register_members_panel(self.hass)
            except Exception:
                panel_status = "注册失败，请查看 HA 系统日志"
                logging.getLogger(__name__).exception("成员管理页面注册失败")

        panel_path = f"/kaadas-members?entry_id={self._entry.entry_id}"
        return self.async_show_form(
            step_id="open_members_editor",
            data_schema=vol.Schema({
                vol.Optional(
                    "成员管理页面地址（点击上方链接，或复制到新标签页）",
                    default=panel_path,
                ): str,
            }),
            description_placeholders={
                "member_manager_url": panel_path,
                "panel_status": panel_status,
            },
            errors={"base": "panel_unavailable"} if panel_status != "已注册" else {},
        )

    async def async_step_members_link(self, user_input=None):
        """Visible copyable fallback if a browser blocks opening a new tab."""
        if user_input is not None:
            return self.async_abort(reason="member_management_opened")
        return self.async_show_form(
            step_id="members_link",
            data_schema=vol.Schema({
                vol.Required(
                    "成员管理网址路径（复制并加在HA网址后）",
                    default=f"/kaadas-members?entry_id={self._entry.entry_id}",
                ): str,
            }),
            description_placeholders={
                "member_manager_url": f"/kaadas-members?entry_id={self._entry.entry_id}",
            },
        )

    async def async_step_confirm_remove(self, user_input=None):
        """Require explicit confirmation before removing one member."""
        selected_id = getattr(self, "_pending_remove_id", None)
        members = self.settings.get("members", [])
        current = next((m for m in members if m.get("id") == selected_id), None)
        if current is None:
            return await self.async_step_members()
        confirmation_key = f"确认删除成员“{str(current.get('name') or '未命名')[:40]}”"
        if user_input is not None:
            if bool(user_input.get(confirmation_key, False)):
                self.settings["members"] = [m for m in members if m.get("id") != selected_id]
                self._pending_remove_id = None
                return self.save()
            self._pending_remove_id = None
            return await self.async_step_members()
        return self.async_show_form(
            step_id="confirm_remove",
            data_schema=vol.Schema({vol.Required(confirmation_key, default=False): bool}),
            description_placeholders={"member_name": str(current.get("name") or "未命名")[:50]},
        )

    async def async_step_add_member(self, user_input=None):
        self.edit_id = None
        return await self.async_step_member(user_input)

    async def choose_member(self, step, user_input):
        members = self.settings.get("members", [])
        if not members:
            return self.async_abort(reason="no_members")
        if user_input is not None:
            self.edit_id = user_input["member_id"]
            if step == "remove_member":
                self.settings["members"] = [m for m in members if m["id"] != self.edit_id]
                return self.save()
            return await self.async_step_member()
        return self.async_show_form(step_id=step, data_schema=vol.Schema({vol.Required("member_id"): vol.In({m["id"]: m["name"] + "（" + m["match_name"] + "）" for m in members})}))

    async def async_step_edit_member(self, user_input=None):
        return await self.choose_member("edit_member", user_input)

    async def async_step_remove_member(self, user_input=None):
        return await self.choose_member("remove_member", user_input)

    async def async_step_member(self, user_input=None):
        members = self.settings.get("members", [])
        current = next((m for m in members if m["id"] == self.edit_id), {})
        errors = {}
        if user_input is not None:
            current_input = {
                "name": str(user_input.get(MEMBER_NAME, "")).strip(),
                "match_name": str(user_input.get(MEMBER_MATCH_NAME, "")).strip(),
                "match_mode": user_input.get(MEMBER_MATCH_MODE, "exact"),
                "feedback": bool(user_input.get(MEMBER_FEEDBACK, True)),
                "notify": bool(user_input.get(MEMBER_NOTIFY, False)),
            }
            if not current_input["name"] or not current_input["match_name"]:
                errors["base"] = "required_value"
            elif is_inside({"userNickname": current_input["match_name"]}, self.settings):
                errors["base"] = "reserved_member"
            elif any(m["id"] != self.edit_id and m["match_name"] == current_input["match_name"] for m in members):
                errors["base"] = "duplicate_member"
            else:
                member = {**current_input, "id": self.edit_id or uuid4().hex}
                self.settings["members"] = [member if m["id"] == self.edit_id else m for m in members] if self.edit_id else members + [member]
                return self.save()
            current = current_input
        fields = {
            vol.Required(MEMBER_NAME, default=current.get("name", "")): str,
            vol.Required(MEMBER_MATCH_NAME, default=current.get("match_name", "")): str,
            vol.Required(MEMBER_MATCH_MODE, default=current.get("match_mode", "exact")): vol.In(MATCH_MODE_OPTIONS),
            vol.Required(MEMBER_FEEDBACK, default=current.get("feedback", True)): bool,
            vol.Required(MEMBER_NOTIFY, default=current.get("notify", False)): bool,
        }
        return self.async_show_form(step_id="member", data_schema=vol.Schema(fields), errors=errors)
