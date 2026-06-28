import random
import re
from uuid import uuid4

import pkce
import requests

from waf_solver import solve_aws_waf_challenge

PROXY_URL = ""
APP_HOST = "app4.paypay.ne.jp"
APP_PARAMS = {"payPayLang": "ja"}
PORTAL_HOST = "www.paypay.ne.jp"

_PENDING_OP_LOGINS: dict[str, "PayPayOpsClient"] = {}


def _normalize_phone(phone: str) -> str:
    return phone.replace("-", "")


def _proxy_config(proxy=None):
    proxy = proxy if proxy is not None else (PROXY_URL or None)
    if isinstance(proxy, str):
        if not proxy.startswith(("http://", "https://")):
            proxy = "http://" + proxy
        return {"http": proxy, "https": proxy}
    return proxy


def _result_code(result: dict) -> str:
    return result.get("header", {}).get("resultCode", "")


def _result_message(result: dict, fallback: str) -> str:
    error = result.get("error", {}) if isinstance(result, dict) else {}
    display = error.get("displayErrorResponse", {}) if isinstance(error, dict) else {}
    title = display.get("title")
    description = display.get("description")
    backend_code = error.get("backendResultCode") or display.get("backendResultCode")
    header_message = result.get("header", {}).get("resultMessage") if isinstance(result, dict) else None

    parts = []
    if title:
        parts.append(str(title))
    if description:
        parts.append(str(description))
    if backend_code:
        parts.append(f"(code: {backend_code})")
    if parts:
        return "\n".join(parts)
    if header_message:
        return str(header_message)
    return fallback


def _raise_if_failed(result: dict, fallback: str):
    if _result_code(result) != "S0000":
        raise PayPayOpsLoginError(_result_message(result, fallback))


def generate_vector(r1, r2, r3, precision=8):
    v1 = f"{random.uniform(*r1):.{precision}f}"
    v2 = f"{random.uniform(*r2):.{precision}f}"
    v3 = f"{random.uniform(*r3):.{precision}f}"
    return f"{v1}_{v2}_{v3}"


def generate_device_state():
    return {
        "device_orientation": generate_vector((2.2, 2.6), (-0.2, -0.05), (-0.05, 0.1)),
        "device_orientation_2": generate_vector((2.0, 2.6), (-0.2, -0.05), (-0.05, 0.2)),
        "device_rotation": generate_vector((-0.8, -0.6), (0.65, 0.8), (-0.12, -0.04)),
        "device_rotation_2": generate_vector((-0.85, -0.4), (0.53, 0.9), (-0.15, -0.03)),
        "device_acceleration": generate_vector((-0.35, 0.0), (-0.01, 0.3), (-0.1, 0.1)),
        "device_acceleration_2": generate_vector((0.01, 0.04), (-0.04, 0.09), (-0.03, 0.1)),
    }


def _build_app_headers(client_uuid: str, device_uuid: str, version: str, access_token: str | None = None) -> dict:
    device_state = generate_device_state()
    headers = {
        "Accept": "*/*",
        "Accept-Charset": "UTF-8",
        "Accept-Encoding": "gzip",
        "Client-Mode": "NORMAL",
        "Client-OS-Release-Version": "10",
        "Client-OS-Type": "ANDROID",
        "Client-OS-Version": "29.0.0",
        "Client-Type": "PAYPAYAPP",
        "Client-UUID": client_uuid,
        "Client-Version": version,
        "Connection": "Keep-Alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Device-Acceleration": device_state["device_acceleration"],
        "Device-Acceleration-2": device_state["device_acceleration_2"],
        "Device-Brand-Name": "KDDI",
        "Device-Hardware-Name": "qcom",
        "Device-In-Call": "false",
        "Device-Lock-App-Setting": "false",
        "Device-Lock-Type": "NONE",
        "Device-Manufacturer-Name": "samsung",
        "Device-Name": "SCV38",
        "Device-Orientation": device_state["device_orientation"],
        "Device-Orientation-2": device_state["device_orientation_2"],
        "Device-Rotation": device_state["device_rotation"],
        "Device-Rotation-2": device_state["device_rotation_2"],
        "Device-UUID": device_uuid,
        "Host": APP_HOST,
        "Is-Emulator": "false",
        "Network-Status": "WIFI",
        "System-Locale": "ja",
        "Timezone": "Asia/Tokyo",
        "User-Agent": f"PaypayApp/{version} Android10",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        headers["content-type"] = "application/json"
    return headers


def _build_portal_page_headers(version: str) -> tuple[dict, str]:
    user_agent = (
        f"Mozilla/5.0 (Linux; Android 10; SCV38 Build/QP1A.190711.020; wv) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/136.0.0.0 "
        f"Mobile Safari/537.36 jp.pay2.app.android/{version}"
    )
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Host": PORTAL_HOST,
        "is-emulator": "false",
        "Pragma": "no-cache",
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Android WebView";v="132"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": user_agent,
        "X-Requested-With": "jp.ne.paypay.android.app",
    }
    return headers, user_agent


def _build_portal_api_headers(version: str, referer: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Cache-Control": "no-cache",
        "Client-Id": "pay2-mobile-app-client",
        "Client-OS-Type": "ANDROID",
        "Client-OS-Version": "29.0.0",
        "Client-Type": "PAYPAYAPP",
        "Client-Version": version,
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Host": PORTAL_HOST,
        "Origin": f"https://{PORTAL_HOST}",
        "Pragma": "no-cache",
        "Referer": referer,
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Android WebView";v="132")',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": (
            f"Mozilla/5.0 (Linux; Android 10; SCV38 Build/QP1A.190711.020; wv) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/136.0.0.0 "
            f"Mobile Safari/537.36 jp.pay2.app.android/{version}"
        ),
        "X-Requested-With": "jp.ne.paypay.android.app",
    }


class PayPayOpsError(Exception):
    pass


class PayPayOpsLoginError(PayPayOpsError):
    pass


class PayPayOpsNetworkError(PayPayOpsError):
    pass


class PayPayOpsClient:
    def __init__(
        self,
        *,
        client_uuid: str | None = None,
        device_uuid: str | None = None,
        access_token: str | None = None,
        proxy=None,
    ):
        self.session = requests.Session()
        self.proxy = _proxy_config(proxy)
        self.version = "5.49.0"
        self.client_uuid = client_uuid or str(uuid4())
        self.device_uuid = device_uuid or str(uuid4())
        self.has_existing_device_uuid = device_uuid is not None
        self.code_verifier: str | None = None
        self.access_token = access_token
        self.refresh_token: str | None = None
        self.headers = _build_app_headers(
            self.client_uuid,
            self.device_uuid,
            self.version,
            access_token=access_token,
        )

    def _request_json(self, method: str, url: str, *, expect_json: bool = True, **kwargs):
        try:
            response = self.session.request(method, url, proxies=self.proxy, timeout=40, **kwargs)
        except requests.RequestException as exc:
            raise PayPayOpsNetworkError(str(exc)) from exc
        if not expect_json:
            return response
        try:
            return response.json()
        except ValueError as exc:
            raise PayPayOpsNetworkError("JSONレスポンスの解析に失敗しました。") from exc

    def _maybe_solve_waf(self, response, headers: dict, url: str, params: dict):
        if response.status_code != 202 or "x-amzn-waf-action" not in response.headers:
            return
        user_agent = headers["User-Agent"]
        aws_waf_token = solve_aws_waf_challenge(response.text, user_agent)
        self.session.cookies.set("aws-waf-token", aws_waf_token, domain=".paypay.ne.jp")
        self._request_json("GET", url, expect_json=False, headers=headers, params=params)

    def _exchange_token_from_redirect(self, redirect_url: str) -> dict:
        code_match = re.search(r"[?&]code=([^&]+)", redirect_url)
        if not code_match or not self.code_verifier:
            raise PayPayOpsLoginError("トークン交換に必要な認証コードが見つかりません。")

        headers = dict(self.headers)
        headers.pop("Device-Lock-Type", None)
        headers.pop("Device-Lock-App-Setting", None)

        token = self._request_json(
            "POST",
            f"https://{APP_HOST}/bff/v2/oauth2/token",
            headers=headers,
            params=APP_PARAMS,
            data={
                "clientId": "pay2-mobile-app-client",
                "redirectUri": "paypay://oauth2/callback",
                "code": code_match.group(1),
                "codeVerifier": self.code_verifier,
            },
        )
        _raise_if_failed(token, "操作系ログイン用トークンの取得に失敗しました。")

        payload = token["payload"]
        self.access_token = payload["accessToken"]
        self.refresh_token = payload["refreshToken"]
        self.headers = _build_app_headers(
            self.client_uuid,
            self.device_uuid,
            self.version,
            access_token=self.access_token,
        )
        return token

    def start_login(self, phone: str, password: str) -> dict:
        phone = _normalize_phone(phone)
        self.code_verifier, code_challenge = pkce.generate_pkce_pair(43)

        par = self._request_json(
            "POST",
            f"https://{APP_HOST}/bff/v2/oauth2/par",
            headers=self.headers,
            params=APP_PARAMS,
            data={
                "clientId": "pay2-mobile-app-client",
                "clientAppVersion": self.version,
                "clientOsVersion": "29.0.0",
                "clientOsType": "ANDROID",
                "redirectUri": "paypay://oauth2/callback",
                "responseType": "code",
                "state": pkce.generate_code_verifier(43),
                "codeChallenge": code_challenge,
                "codeChallengeMethod": "S256",
                "scope": "REGULAR",
                "tokenVersion": "v2",
                "prompt": "",
                "uiLocales": "ja",
            },
        )
        _raise_if_failed(par, "操作系ログインの初期化に失敗しました。")

        page_headers, _ = _build_portal_page_headers(self.version)
        authorize_params = {
            "client_id": "pay2-mobile-app-client",
            "request_uri": par["payload"]["requestUri"],
        }
        authorize_response = self._request_json(
            "GET",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/authorize",
            expect_json=False,
            headers=page_headers,
            params=authorize_params,
        )
        self._maybe_solve_waf(
            authorize_response,
            page_headers,
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/authorize",
            authorize_params,
        )

        signin_page_params = {
            "client_id": "pay2-mobile-app-client",
            "mode": "landing",
        }
        signin_page_response = self._request_json(
            "GET",
            f"https://{PORTAL_HOST}/portal/oauth2/sign-in",
            expect_json=False,
            headers=page_headers,
            params=signin_page_params,
        )
        self._maybe_solve_waf(
            signin_page_response,
            page_headers,
            f"https://{PORTAL_HOST}/portal/oauth2/sign-in",
            signin_page_params,
        )

        sign_in_referer = f"https://{PORTAL_HOST}/portal/oauth2/sign-in?client_id=pay2-mobile-app-client&mode=landing"
        portal_headers = _build_portal_api_headers(self.version, sign_in_referer)

        par_check = self._request_json(
            "GET",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/par/check",
            headers=portal_headers,
        )
        _raise_if_failed(par_check, "操作系ログインの状態確認に失敗しました。")

        signin = self._request_json(
            "POST",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/sign-in/password",
            headers=portal_headers,
            json={
                "username": phone,
                "password": password,
                "signInAttemptCount": 1,
            },
        )
        _raise_if_failed(signin, "操作系ログインに失敗しました。")

        if self.has_existing_device_uuid:
            redirect_url = signin.get("payload", {}).get("redirectUrl")
            if not redirect_url:
                raise PayPayOpsLoginError("保存されている操作用 Device UUID が無効です。")
            token = self._exchange_token_from_redirect(redirect_url)
            return {
                "status": "OK",
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "client_uuid": self.client_uuid,
                "device_uuid": self.device_uuid,
                "raw": token,
            }

        code_update = self._request_json(
            "POST",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/extension/code-grant/update",
            headers=portal_headers,
            json={},
        )
        _raise_if_failed(code_update, "2段階認証の初期化に失敗しました。")

        otl_select_headers = _build_portal_api_headers(
            self.version,
            f"https://{PORTAL_HOST}/portal/oauth2/verification-method?client_id=pay2-mobile-app-client&mode=navigation-2fa",
        )
        nav_2fa = self._request_json(
            "POST",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/extension/code-grant/update",
            headers=otl_select_headers,
            json={
                "params": {
                    "extension_id": "user-main-2fa-v1",
                    "data": {
                        "type": "SELECT_FLOW",
                        "payload": {
                            "flow": "OTL",
                            "sign_in_method": "MOBILE",
                            "base_url": f"https://{PORTAL_HOST}/portal/oauth2/l",
                        },
                    },
                }
            },
        )
        _raise_if_failed(nav_2fa, "2段階認証方式の選択に失敗しました。")

        otl_request_headers = _build_portal_api_headers(
            self.version,
            f"https://{PORTAL_HOST}/portal/oauth2/otl-request?client_id=pay2-mobile-app-client&mode=navigation-2fa",
        )
        otl_request = self._request_json(
            "POST",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/extension/code-grant/side-channel/next-action-polling",
            headers=otl_request_headers,
            json={"waitUntil": "PT5S"},
        )
        _raise_if_failed(otl_request, "2段階認証URLの発行待機に失敗しました。")

        return {
            "status": "PENDING_2FA",
            "client_uuid": self.client_uuid,
            "device_uuid": self.device_uuid,
        }

    def complete_2fa(self, otl_url: str) -> dict:
        token = otl_url.replace(f"https://{PORTAL_HOST}/portal/oauth2/l?id=", "").strip()
        if not token:
            raise PayPayOpsLoginError("認証URLが空です。")

        referer = f"https://{PORTAL_HOST}/portal/oauth2/l?id={token}&client_id=pay2-mobile-app-client"
        headers = _build_portal_api_headers(self.version, referer)

        confirm = self._request_json(
            "POST",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/extension/sign-in/2fa/otl/verify",
            headers=headers,
            json={"code": token},
        )
        _raise_if_failed(confirm, "2段階認証URLの確認に失敗しました。")

        redirect_result = self._request_json(
            "POST",
            f"https://{PORTAL_HOST}/portal/api/v2/oauth2/extension/code-grant/update",
            headers=headers,
            json={
                "params": {
                    "extension_id": "user-main-2fa-v1",
                    "data": {
                        "type": "COMPLETE_OTL",
                        "payload": None,
                    },
                }
            },
        )
        _raise_if_failed(redirect_result, "2段階認証の完了処理に失敗しました。")

        redirect_uri = redirect_result.get("payload", {}).get("redirect_uri")
        if not redirect_uri:
            raise PayPayOpsLoginError("2段階認証後のリダイレクトURLが取得できませんでした。")

        token_result = self._exchange_token_from_redirect(redirect_uri)
        return {
            "status": "OK",
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "client_uuid": self.client_uuid,
            "device_uuid": self.device_uuid,
            "raw": token_result,
        }

    def refresh_access_token(self, refresh_token: str) -> dict:
        if not refresh_token:
            raise PayPayOpsLoginError("操作系リフレッシュトークンが保存されていません。")

        result = self._request_json(
            "POST",
            f"https://{APP_HOST}/bff/v2/oauth2/refresh",
            headers=self.headers,
            params=APP_PARAMS,
            data={
                "clientId": "pay2-mobile-app-client",
                "refreshToken": refresh_token,
                "tokenVersion": "v2",
            },
        )
        if _result_code(result) in {"S0001", "S0003", "S1003"}:
            raise PayPayOpsLoginError(_result_message(result, "操作系セッションの更新に失敗しました。"))
        if _result_code(result) != "S0000":
            raise PayPayOpsError(_result_message(result, "操作系セッションの更新に失敗しました。"))

        payload = result["payload"]
        self.access_token = payload["accessToken"]
        self.refresh_token = payload["refreshToken"]
        self.headers = _build_app_headers(
            self.client_uuid,
            self.device_uuid,
            self.version,
            access_token=self.access_token,
        )
        return result

    def get_balance(self) -> dict:
        if not self.access_token:
            return {
                "header": {
                    "resultCode": "S9999",
                    "resultMessage": "操作系アクセストークンがありません。",
                }
            }

        try:
            return self._request_json(
                "GET",
                f"https://{APP_HOST}/bff/v1/getBalanceInfo",
                headers=self.headers,
                params={
                    "includePendingBonusLite": "false",
                    "includePending": "true",
                    "noCache": "true",
                    "includeKycInfo": "true",
                    "includePayPaySecuritiesInfo": "true",
                    "includePointInvestmentInfo": "true",
                    "includePayPayBankInfo": "true",
                    "includeGiftVoucherInfo": "true",
                    "payPayLang": "ja",
                },
            )
        except PayPayOpsNetworkError as exc:
            return {
                "header": {
                    "resultCode": "NETWORK_ERROR",
                    "resultMessage": str(exc),
                }
            }


def start_login(
    phone: str,
    password: str,
    client_uuid: str | None = None,
    device_uuid: str | None = None,
    proxy=None,
) -> dict:
    client = PayPayOpsClient(client_uuid=client_uuid, device_uuid=device_uuid, proxy=proxy)
    result = client.start_login(phone, password)
    if result["status"] == "PENDING_2FA":
        state_id = str(uuid4())
        _PENDING_OP_LOGINS[state_id] = client
        result["state_id"] = state_id
    return result


def complete_login(state_id: str, otl_url: str) -> dict:
    client = _PENDING_OP_LOGINS.pop(state_id, None)
    if not client:
        raise PayPayOpsLoginError("操作系ログインの途中状態が見つかりません。`/paypay操作ログイン` を最初からやり直してください。")
    return client.complete_2fa(otl_url)


def refresh_access_token(
    refresh_token: str,
    client_uuid: str,
    device_uuid: str,
    access_token: str | None = None,
    proxy=None,
) -> dict:
    client = PayPayOpsClient(
        client_uuid=client_uuid,
        device_uuid=device_uuid,
        access_token=access_token,
        proxy=proxy,
    )
    return client.refresh_access_token(refresh_token)


def get_balance(
    access_token: str,
    client_uuid: str,
    device_uuid: str,
    proxy=None,
) -> dict:
    client = PayPayOpsClient(
        client_uuid=client_uuid,
        device_uuid=device_uuid,
        access_token=access_token,
        proxy=proxy,
    )
    return client.get_balance()
