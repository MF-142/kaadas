"""凯迪仕账号认证客户端。

仅负责账号认证、验证码处理和已绑定设备信息读取。
不包含远程开锁功能；诊断信息不记录账户凭证或请求细节。
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from yarl import URL

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

API_BASE = "https://app.kaadas.com:34000"
LOGIN_VER = "20230913"
DEVICE_VER = "20231127"
DEFAULT_APP_VERSION = "6.21.0.7"
# 通用客户端参数：不包含具体手机型号、系统版本或网络栈指纹。
DEFAULT_OS_VERSION = "0.0"
DEFAULT_PHONE_NAME = "iPhone"
DEFAULT_UA = "KaadasLock/6.21.0 (iPhone)"
CAPTCHA_UA = "KaadasLock/7"
DEFAULT_TERMINAL_NAME = "iPhone"


class ProtocolError(Exception):
    """API通信或响应结构问题；公开描述不能含凭证。"""


@dataclass
class LoginOutcome:
    ok: bool
    code: str
    message: str
    token: str = ""
    uid: str = ""
    challenge_needed: bool = False


def normalize_account(account: str, mode: str = "auto86") -> str:
    """Account formatting is a *user-visible choice*. Never auto-test variants."""
    raw = account.strip()
    if mode not in ("auto86", "as_entered"):
        raise ProtocolError("账号格式选项无效")
    if mode == "auto86" and re.fullmatch(r"1\d{10}", raw):
        return "86" + raw
    return raw


def compact_json_dumps(value: dict) -> str:
    """生成紧凑 JSON 请求内容，并保持斜杠转义格式。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("/", "\\/")


def is_challenge_response(code: str, message: str) -> bool:
    """只对响应明确提示的验证码/二次验证转移；code 101 不自动转移。"""
    msg = (message or "").lower()
    return any(word in msg for word in ("验证码", "图形码", "图形验证", "安全验证", "异常验证", "captcha", "verify code"))


def encrypt_rsa_spki(data_b64: str, plain_text: str, pad_mode: str) -> str:
    """按服务器返回的认证材料生成加密字段。"""
    try:
        binary = base64.b64decode(data_b64, validate=True)
        pub = serialization.load_der_public_key(binary)
    except (ValueError, TypeError) as exc:
        raise ProtocolError("服务器认证材料格式无效") from exc
    if not isinstance(pub, rsa.RSAPublicKey):
        raise ProtocolError("服务器认证材料类型不受支持")
    if pad_mode == "PKCS1v15":
        pad = padding.PKCS1v15()
    elif pad_mode == "OAEP-SHA1":
        pad = padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
    elif pad_mode == "OAEP-SHA256":
        pad = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    else:
        raise ProtocolError("当前认证参数不受支持")
    try:
        return base64.b64encode(pub.encrypt(plain_text.encode("utf-8"), pad)).decode("ascii")
    except ValueError as exc:
        raise ProtocolError("登录信息长度超出服务器允许范围") from exc


def parse_response(payload: Any) -> LoginOutcome:
    if not isinstance(payload, dict):
        raise ProtocolError("登录返回不是JSON对象")
    code = str(payload.get("code", ""))
    msg = str(payload.get("msg", ""))[:120]
    # 避免服务器意外把敏感数据带进 msg 的展示路径。
    if len(msg) > 80 or any(x in msg.lower() for x in ("token", "password", "cookie", "密钥", "密文")):
        msg = "服务端认证提示（详情已隐藏）"
    else:
        msg = re.sub(r"(?<!\d)(?:86)?1[3-9]\d{9}(?!\d)", "[手机号已隐藏]", msg)
        msg = re.sub(r"(?:[A-Za-z0-9+/]{28,}={0,2})", "[敏感字段已隐藏]", msg)
    if code != "200":
        return LoginOutcome(False, code or "unknown", msg, challenge_needed=is_challenge_response(code, msg))
    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("token") or not data.get("uid"):
        raise ProtocolError("登录返回200，但未包含可用的token和uid")
    return LoginOutcome(True, code, "登录成功", token=str(data["token"]), uid=str(data["uid"]))


class KaadasClient:
    """独立CookieJar，保证同一登录流程内验证码会话一致。"""

    def __init__(
        self,
        *,
        account: str,
        password: str,
        normal_account_mode: str = "as_entered",
        captcha_account_mode: str = "auto86",
        padding_mode: str = "PKCS1v15",
        phone_name: str = DEFAULT_PHONE_NAME,
        user_agent: str = DEFAULT_UA,
        app_version: str = DEFAULT_APP_VERSION,
        os_version: str = DEFAULT_OS_VERSION,
        unique_code: str | None = None,
        device_user_agent: str | None = None,
        device_phone_name: str | None = None,
    ) -> None:
        self.account = account.strip()
        self.normal_account_mode = normal_account_mode
        self.captcha_account_mode = captcha_account_mode
        self.normal_account = normalize_account(account, normal_account_mode)
        self.captcha_account = normalize_account(account, captcha_account_mode)
        self.password = password
        self.padding_mode = padding_mode
        self.phone_name = phone_name
        self.user_agent = user_agent
        self.app_version = app_version
        self.os_version = os_version
        self.unique_code = unique_code or str(uuid.uuid4()).upper()
        self.device_user_agent = device_user_agent or user_agent
        self.device_phone_name = device_phone_name or phone_name
        self._cookie_jar = aiohttp.CookieJar()
        self._session: aiohttp.ClientSession | None = None
        self.trace: list[dict[str, Any]] = []
        self.public_key_b64 = ""
        self.token = ""
        self.uid = ""

    def clear_password(self) -> None:
        self.password = ""

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                cookie_jar=self._cookie_jar,
                timeout=aiohttp.ClientTimeout(total=12),
                trust_env=False,
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        self.clear_password()

    def _record(self, *, step: str, method: str, path: str, headers: dict,
                body: dict | None, code: str | None = None,
                http_status: int | None = None, elapsed_ms: int | None = None,
                response_type: str | None = None,
                request_cookie_sent: bool | None = None, response_set_cookie: bool | None = None) -> None:
        """仅记录必要的运行结果，不保存请求地址、字段名、请求头或凭证。"""
        self.trace.append({
            "step": step,
            "http_status": http_status,
            "business_code": code,
            "elapsed_ms": elapsed_ms,
            "response_type": response_type,
        })

    def diagnostic_snapshot(self) -> dict:
        """返回经过精简的运行状态，不包含账号、凭证或内部请求细节。"""
        return {"trace": list(self.trace)}

    def _common_headers(self, ver: str) -> dict[str, str]:
        return {
            "uniqueCode": self.unique_code,
            "kds-debug": "1",
            "Accept-Language": "zh-Hans-CN;q=1, en-CN;q=0.9, zh-Hant-CN;q=0.8",
            "clientOSVersion": self.os_version,
            "terminalModel": self.phone_name,
            "clientAPPVersion": self.app_version,
            "ver": ver,
            "reqSource": "app",
            "lang": "zh_CN",
            "User-Agent": self.user_agent,
            "terminalName": DEFAULT_TERMINAL_NAME,
            "phoneName": self.phone_name,
            "Accept": "*/*",
        }

    async def _request_json(self, method: str, path: str, *,
                            headers: dict | None = None,
                            json_body: dict | None = None,
                            query: dict[str, str] | None = None) -> dict:
        headers = dict(headers or {})
        if json_body is not None:
            headers.setdefault("Content-Type", "application/json")
            body_bytes = compact_json_dumps(json_body).encode("utf-8")
        else:
            body_bytes = None
        started = time.monotonic()
        http_status = None
        # BEFORE the request, check what the cookie jar would attach for this URL.
        # Previous versions incorrectly recorded cookies AFTER the response.
        cookie_sent = bool(self._cookie_jar.filter_cookies(URL(API_BASE + path)))
        try:
            session = self._get_session()
            async with session.request(method, API_BASE + path, headers=headers, data=body_bytes, params=query) as response:
                http_status = response.status
                if response.status != 200:
                    raise ProtocolError(f"HTTP状态异常：{response.status}")
                obj = await response.json(content_type=None)
                if not isinstance(obj, dict):
                    raise ProtocolError("服务端JSON格式异常")
                self._record(step="json", method=method, path=path, headers=headers,
                             body=json_body, code=str(obj.get("code", "")),
                             http_status=http_status,
                             elapsed_ms=round((time.monotonic() - started) * 1000),
                             response_type="application/json",
                             request_cookie_sent=cookie_sent,
                             response_set_cookie=bool(response.cookies))
                return obj
        except (aiohttp.ClientError, TimeoutError) as exc:
            self._record(step="json_error", method=method, path=path, headers=headers,
                         body=json_body, http_status=http_status)
            raise ProtocolError("连接凯迪仕服务器失败或超时") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            self._record(step="json_error", method=method, path=path, headers=headers,
                         body=json_body, http_status=http_status)
            raise ProtocolError("服务器响应无法解析为JSON") from exc

    async def fetch_public_key(self) -> int:
        obj = await self._request_json("GET", "/app/user/login/rsa/publicKey", headers=self._common_headers(LOGIN_VER))
        if str(obj.get("code")) != "200" or not isinstance(obj.get("data"), str):
            raise ProtocolError("认证准备未能完成")
        try:
            pub = serialization.load_der_public_key(base64.b64decode(obj["data"], validate=True))
        except (TypeError, ValueError) as exc:
            raise ProtocolError("认证材料格式无效") from exc
        if not isinstance(pub, rsa.RSAPublicKey):
            raise ProtocolError("认证材料类型不受支持")
        self.public_key_b64 = obj["data"]
        return pub.key_size

    def _encrypted(self, value: str) -> str:
        if not self.public_key_b64:
            raise ProtocolError("认证准备尚未完成")
        return encrypt_rsa_spki(self.public_key_b64, value, self.padding_mode)

    async def fetch_nonce(self, account: str) -> str:
        """获取本次登录所需的临时认证数据。"""
        encrypted_username = self._encrypted(account)
        obj = await self._request_json(
            "GET", "/app/user/nonce", headers=self._common_headers(LOGIN_VER),
            query={"username": encrypted_username},
        )
        if str(obj.get("code")) != "200" or not isinstance(obj.get("data"), str) or not obj["data"]:
            raise ProtocolError("认证请求未返回有效结果；业务码：" + str(obj.get("code", "unknown"))[:12])
        return obj["data"]

    def _encrypted_password_envelope(self, nonce: str) -> str:
        """生成当前登录请求使用的临时认证数据。"""
        envelope = {
            "pwd": self.password,
            "n": nonce,
            "t": time.time_ns() // 1_000_000,
        }
        payload = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        return self._encrypted(payload)

    def _login_headers(self) -> dict[str, str]:
        """构造登录请求所需的通用请求头。"""
        return {**self._common_headers(LOGIN_VER),
                "Content-Type": "application/json",
                "timestamp": str(time.time_ns() // 1_000_000)}

    async def login_normal(self) -> LoginOutcome:
        nonce = await self.fetch_nonce(self.normal_account)
        # 登录请求中的账号字段与密码字段分别按既有流程生成。
        body = {
            "tel": self._encrypted(self.normal_account),
            "encrypt": 1,
            "password": self._encrypted_password_envelope(nonce),
        }
        obj = await self._request_json(
            "POST", "/app/user/login/getuserbytel",
            headers=self._login_headers(), json_body=body,
        )
        result = parse_response(obj)
        if result.ok:
            self.token, self.uid = result.token, result.uid
            self.clear_password()
        return result

    async def fetch_captcha(self) -> bytes:
        # 验证码请求与当前登录流程共用同一会话。
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": CAPTCHA_UA,
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        }
        body = {"name": self.captcha_account}
        started = time.monotonic()
        http_status = None
        captcha_path = "/app/user/login/graphicalCode"
        cookie_sent = bool(self._cookie_jar.filter_cookies(URL(API_BASE + captcha_path)))
        try:
            async with self._get_session().post(
                API_BASE + "/app/user/login/graphicalCode",
                data=compact_json_dumps(body).encode("utf-8"),
                headers=headers,
            ) as response:
                http_status = response.status
                if response.status != 200:
                    raise ProtocolError(f"获取验证码失败：HTTP {response.status}")
                content_type = response.headers.get("Content-Type", "").lower()
                jpeg = await response.read()
                if "image/jpeg" not in content_type or not jpeg.startswith(b"\xff\xd8"):
                    raise ProtocolError("验证码接口没有返回有效JPEG图片")
                if not (128 <= len(jpeg) <= 100_000):
                    raise ProtocolError("验证码图片尺寸异常")
                self._record(step="captcha", method="POST",
                             path="/app/user/login/graphicalCode", headers=headers,
                             body=body, http_status=http_status,
                             elapsed_ms=round((time.monotonic() - started) * 1000),
                             response_type="image/jpeg",
                             request_cookie_sent=cookie_sent,
                             response_set_cookie=bool(response.cookies))
                return jpeg
        except (aiohttp.ClientError, TimeoutError) as exc:
            self._record(step="captcha_error", method="POST",
                         path="/app/user/login/graphicalCode", headers=headers,
                         body=body, http_status=http_status)
            raise ProtocolError("获取验证码时连接失败或超时") from exc

    async def login_abnormal(self, code: str) -> LoginOutcome:
        code = code.strip()
        if not code or len(code) > 12:
            raise ProtocolError("请填写有效验证码")
        nonce = await self.fetch_nonce(self.captcha_account)
        # Match the successful capture key order; change password envelope only.
        body = {
            "password": self._encrypted_password_envelope(nonce),
            "code": code,
            "name": self._encrypted(self.captcha_account),
            "encrypt": 1,
        }
        obj = await self._request_json(
            "POST", "/app/user/login/abnormal",
            headers=self._login_headers(), json_body=body,
        )
        result = parse_response(obj)
        if result.ok:
            self.token, self.uid = result.token, result.uid
            self.clear_password()
        return result

    async def fetch_devices(self) -> list[dict]:
        if not self.token or not self.uid:
            raise ProtocolError("尚未成功登录，无法查询绑定设备")
        headers = {**self._common_headers(DEVICE_VER), "token": self.token, "Content-Type": "application/json"}
        headers["User-Agent"] = self.device_user_agent
        headers["phoneName"] = self.device_phone_name
        result = await self._request_json(
            "POST", "/app/user/findAllBindDevice", headers=headers,
            json_body={"uid": self.uid, "modelSearchType": 2},
        )
        if str(result.get("code")) != "200":
            raise ProtocolError("设备信息查询失败，业务码：" + str(result.get("code", "unknown"))[:20])
        data = result.get("data")
        if not isinstance(data, dict):
            raise ProtocolError("设备信息data不是对象")
        wifi_list = data.get("wifiList")
        if not isinstance(wifi_list, list):
            raise ProtocolError("设备信息缺少wifiList数组")
        out = []
        for row in wifi_list:
            if not isinstance(row, dict):
                continue
            # 仅导出已知字段；不把整个服务端响应复制到HA。
            out.append({key: row.get(key) for key in (
                "wifiSN", "productModel", "lockNickname", "adminName", "wifiAddress",
                "camera_version", "wifiName", "power", "openCount"
            )})
        return out


def safe_summary(devices: list[dict]) -> list[dict]:
    """用户可分享的脱敏结果，避免UID、token、MAC、SSID与精确设备序列号泄露。"""
    return [{
        "lock_name": d.get("lockNickname"),
        "product_model": d.get("productModel"),
        "power": d.get("power"),
        "open_count": d.get("openCount"),
        "camera_version": d.get("camera_version"),
        "has_wifi_sn": bool(d.get("wifiSN")),
        "has_wifi_address": bool(d.get("wifiAddress")),
        "has_wifi_name": bool(d.get("wifiName")),
    } for d in devices]
