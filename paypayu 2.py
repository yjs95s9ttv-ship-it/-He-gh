import aiohttp
import base64
import datetime
import hashlib
import secrets
import urllib.parse
import uuid as uuid_lib

from useragent_changer import UserAgent
from yarl import URL

ua = UserAgent("iphone")

PROXY_URL = ""
APP_VERSION = "5.11.1"
APP_HOST = "app4.paypay.ne.jp"
APP_PARAMS = {"payPayLang": "ja"}
_LOGIN_STATES: dict[str, dict] = {}


def _proxy():
    return PROXY_URL or None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def _normalize_phone(phone_number: str) -> str:
    return phone_number.replace("-", "")


def _now_jst() -> str:
    return datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))
    ).strftime("%Y-%m-%dT%H:%M:%S+0900")


def _app_headers(client_uuid: str, device_uuid: str, access_token: str | None = None, *, form: bool = False) -> dict:
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
        "Client-Version": APP_VERSION,
        "Connection": "Keep-Alive",
        "Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
        "Device-Brand-Name": "KDDI",
        "Device-Hardware-Name": "qcom",
        "Device-Manufacturer-Name": "samsung",
        "Device-Name": "SCV38",
        "Device-UUID": device_uuid,
        "Host": APP_HOST,
        "Is-Emulator": "false",
        "Network-Status": "WIFI",
        "System-Locale": "ja",
        "Timezone": "Asia/Tokyo",
        "User-Agent": f"PaypayApp/{APP_VERSION} Android10",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _portal_headers(referer: str) -> dict:
    return {
        "Host": "www.paypay.ne.jp",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "Client-Os-Version": "29.0.0",
        "Client-Version": APP_VERSION,
        "User-Agent": f"Mozilla/5.0 (Linux; Android 10; SCV38 Build/QP1A.190711.020; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/132.0.6834.163 Mobile Safari/537.36 jp.pay2.app.android/{APP_VERSION}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Client-Os-Type": "ANDROID",
        "Client-Id": "pay2-mobile-app-client",
        "Client-Type": "PAYPAYAPP",
        "Origin": "https://www.paypay.ne.jp",
        "X-Requested-With": "jp.ne.paypay.android.app",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": referer,
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    }


def _error_response(message: str, raw: dict | None = None) -> dict:
    result = {
        "response_type": "ErrorResponse",
        "error_description": message,
        "header": {
            "resultCode": "S9999",
            "resultMessage": message,
        },
    }
    if raw is not None:
        result["raw"] = raw
    return result


def _extract_error_message(raw: dict, fallback: str) -> str:
    error = raw.get("error", {}) if isinstance(raw, dict) else {}
    display = error.get("displayErrorResponse", {}) if isinstance(error, dict) else {}

    title = display.get("title")
    description = display.get("description")
    backend_code = error.get("backendResultCode") or display.get("backendResultCode")
    header_message = raw.get("header", {}).get("resultMessage") if isinstance(raw, dict) else None

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


async def _json_request(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> dict:
    try:
        async with session.request(method, url, **kwargs) as response:
            return await response.json(content_type=None)
    except aiohttp.ClientError as exc:
        return {
            "header": {
                "resultCode": "NETWORK_ERROR",
                "resultMessage": str(exc),
            }
        }


async def _exchange_token(session: aiohttp.ClientSession, client_uuid: str, device_uuid: str, code: str, verifier: str) -> dict:
    payload = {
        "clientId": "pay2-mobile-app-client",
        "redirectUri": "paypay://oauth2/callback",
        "code": code,
        "codeVerifier": verifier,
    }
    return await _json_request(
        session,
        "POST",
        f"https://{APP_HOST}/bff/v2/oauth2/token",
        params=APP_PARAMS,
        headers=_app_headers(client_uuid, device_uuid, form=True),
        data=payload,
        proxy=_proxy(),
    )


async def _authorized_app_request(method: str, path: str, access_token: str, client_uuid: str, *, params: dict | None = None, payload: dict | None = None) -> dict:
    headers = _app_headers(client_uuid, client_uuid, access_token)
    merged_params = dict(APP_PARAMS)
    if params:
        merged_params.update(params)

    async with aiohttp.ClientSession() as session:
        return await _json_request(
            session,
            method,
            f"https://{APP_HOST}{path}",
            headers=headers,
            params=merged_params,
            json=payload,
            proxy=_proxy(),
        )


async def login(phoneNumber: str, password: str, uuid: str):
    headers = {
        "User-Agent": ua.set(),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.paypay.ne.jp",
        "Referer": "https://www.paypay.ne.jp/app/account/sign-in",
    }
    payload = {
        "scope": "SIGN_IN",
        "client_uuid": f"{uuid}",
        "grant_type": "password",
        "username": phoneNumber,
        "password": password,
        "add_otp_prefix": True,
        "language": "ja",
    }
    async with aiohttp.ClientSession() as session:
        response = await _json_request(
            session,
            "POST",
            "https://www.paypay.ne.jp/app/v1/oauth/token",
            headers=headers,
            json=payload,
            proxy=_proxy(),
        )
    if response.get("response_type") == "ErrorResponse":
        result_info = response.get("result_info", {})
        response["error_description"] = result_info.get("result_msg", "ログインに失敗しました。")
    return response


async def login_otp_raw(set_uuid, otp, otpid=None, otp_pre=None):
    headers = {
        "User-Agent": ua.set(),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.paypay.ne.jp",
        "Referer": "https://www.paypay.ne.jp/app/account/sign-in",
    }
    payload = {
        "scope": "SIGN_IN",
        "client_uuid": f"{set_uuid}",
        "grant_type": "otp",
        "otp_prefix": str(otp_pre) if otp_pre is not None else None,
        "otp": str(otp),
        "otp_reference_id": otpid,
        "username_type": "MOBILE",
        "language": "ja",
    }
    async with aiohttp.ClientSession() as session:
        response = await _json_request(
            session,
            "POST",
            "https://www.paypay.ne.jp/app/v1/oauth/token",
            headers=headers,
            json=payload,
            proxy=_proxy(),
        )
    if response.get("response_type") == "ErrorResponse":
        result_info = response.get("result_info", {})
        response["error_description"] = result_info.get("result_msg", "OTPコードが正しくありません。")
    return response


async def login_otp(set_uuid, otp, otpid, otp_pre):
    result = await login_otp_raw(set_uuid, otp, otpid, otp_pre)
    if result.get("response_type") == "ErrorResponse":
        return "ERR"
    return "OK"


async def get_balance(access_token: str, uuid: str):
    return await _authorized_app_request(
        "GET",
        "/bff/v1/getBalanceInfo",
        access_token,
        uuid,
        params={
            "includePendingBonusLite": "false",
            "includePending": "true",
            "noCache": "true",
            "includeKycInfo": "true",
            "includePayPaySecuritiesInfo": "true",
            "includePointInvestmentInfo": "true",
            "includePayPayBankInfo": "true",
            "includeGiftVoucherInfo": "true",
        },
    )


async def get_history(access_token: str, uuid: str, page_size: int = 20):
    return await _authorized_app_request(
        "GET",
        "/bff/v3/getPaymentHistory",
        access_token,
        uuid,
        params={
            "pageSize": str(page_size),
            "orderTypes": "",
            "paymentMethodTypes": "",
            "signUpCompletedAt": "2021-01-02T10:16:24Z",
            "isOverdraftOnly": "false",
        },
    )


async def get_profile(access_token: str, uuid: str):
    return await _authorized_app_request(
        "GET",
        "/bff/v2/getProfileDisplayInfo",
        access_token,
        uuid,
        params={
            "includeExternalProfileSync": "true",
            "completedOptionalTasks": "ENABLED_NEARBY_DEALS",
        },
    )


async def create_mycode(access_token: str, uuid: str):
    return await _authorized_app_request(
        "POST",
        "/bff/v1/createP2PCode",
        access_token,
        uuid,
        payload={"amount": None, "sessionId": None},
    )


async def create_link(access_token: str, uuid: str, amount: int, passcode: str | None = None):
    payload = {
        "requestId": str(uuid_lib.uuid4()),
        "amount": amount,
        "socketConnection": "P2P",
        "theme": "default-sendmoney",
        "source": "sendmoney_home_sns",
    }
    if passcode:
        payload["passcode"] = passcode

    return await _authorized_app_request(
        "POST",
        "/bff/v2/executeP2PSendMoneyLink",
        access_token,
        uuid,
        payload=payload,
    )


async def accept_link(access_token: str, uuid: str, link: str, passcode: str | None = None):
    verification_code = link.replace("https://pay.paypay.ne.jp/", "") if "https://" in link else link
    link_info = await _authorized_app_request(
        "GET",
        "/bff/v2/getP2PLinkInfo",
        access_token,
        uuid,
        params={"verificationCode": verification_code},
    )
    if link_info.get("header", {}).get("resultCode") != "S0000":
        return link_info
    if link_info.get("payload", {}).get("orderStatus") != "PENDING":
        return {
            "header": {
                "resultCode": "S9999",
                "resultMessage": "このリンクは既に処理されています。",
            }
        }

    payload = {
        "requestId": str(uuid_lib.uuid4()),
        "orderId": link_info["payload"]["pendingP2PInfo"]["orderId"],
        "verificationCode": verification_code,
        "senderMessageId": link_info["payload"]["message"]["messageId"],
        "senderChannelUrl": link_info["payload"]["message"]["chatRoomId"],
    }
    if link_info.get("payload", {}).get("pendingP2PInfo", {}).get("isSetPasscode"):
        if not passcode:
            return {
                "header": {
                    "resultCode": "S9999",
                    "resultMessage": "このリンクにはパスコードが必要です。",
                }
            }
        payload["passcode"] = passcode

    return await _authorized_app_request(
        "POST",
        "/bff/v2/acceptP2PSendMoneyLink",
        access_token,
        uuid,
        params={"appContext": "P2PMoneyTransferDetailScreen_linkReceiver"},
        payload=payload,
    )

async def check_link(cd):
    if "https://" in cd:
        cd=cd.replace("https://pay.paypay.ne.jp/","")

    headers={
        "Accept":"application/json, text/plain, */*",
        'User-Agent': ua.set(),
        "Content-Type":"application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://www.paypay.ne.jp/app/v2/p2p-api/getP2PLinkInfo?verificationCode={cd}", headers=headers, proxy=PROXY_URL) as response:
                response.raise_for_status()
                link_info = await response.json()
            
        except aiohttp.ClientError as e:
            print(f"API_REQ_EXC: {e}") #debug :)
            return False
    
    result_code = link_info.get("header", {}).get("resultCode")
    if result_code != "S0000":
        # ãªã¶ã«ãã³ã¼ããS0000ä»¥å¤ã ã£ãå ´åã¯åºæ¬ä½ãã¨ã©ã¼èµ·ãã¦ã
        return False

    order_status = link_info.get("payload", {}).get("orderStatus")
    if order_status == "PENDING":
        # ååå¾ã¡ã ã£ããlink_infoãè¿ãããããªãã£ããåãåããã¦ãorã­ã£ã³ã»ã«ããã¦ãor...ããFalse
        return link_info
    else:
        return False
    
async def link_rev(cd: str, phoneNumber: str, password: str, uuid: str,link_password: str = None):
    if "https://" in cd:
        cd=cd.replace("https://pay.paypay.ne.jp/","")
        
    async with aiohttp.ClientSession() as session:
        base_headers = {
            "Accept": "application/json, text/plain, */*",
            'User-Agent': ua.set(),
            "Content-Type": "application/json"
        }
        
        try:
            async with session.get(f"https://www.paypay.ne.jp/app/v2/p2p-api/getP2PLinkInfo?verificationCode={cd}", headers=base_headers, proxy=PROXY_URL) as response:
                response.raise_for_status()
                link_info = await response.json()

            if link_info.get("payload", {}).get("orderStatus") != "PENDING":
                # ããã§ãååå¾ã¡ããã§ãã¯ãååå¾ã¡ãããªãã£ããå¼¾ã
                return False
            
            if link_info.get("payload", {}).get("pendingP2PInfo", {}).get("isSetPasscode") and link_password is None:
                return False

        except aiohttp.ClientError as e:
            print(f"LINK_REQ_EXC: {e}") #debug :)
            return False
        
        login_payload = {
            "scope":"SIGN_IN",
            "client_uuid":f"{uuid}",
            "grant_type":"password",
            "username":phoneNumber,
            "password":password,
            "add_otp_prefix": True,
            "language":"ja"
            }

        login_headers = {
            'User-Agent': ua.set(),
            'Accept' : 'application/json, text/plain, */*',
            'Content-Type' : 'application/json',
            'Origin': 'https://www.paypay.ne.jp',
            'Referer':'https://pay.paypay.ne.jp/'+cd,
        }

        async with session.post("https://www.paypay.ne.jp/app/v1/oauth/token", headers=login_headers, json=login_payload, proxy=PROXY_URL) as response:
            login_response = await response.json()
            try:
                login_response = (login_response["access_token"])
            except:
                try:
                    login_response["otp_reference_id"]
                    return "LOGINERR"
                except:
                    return "LOGINERR"
        
        receive_payload = {
            "verificationCode":cd,
            "client_uuid":uuid,
            "requestAt":str(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%dT%H:%M:%S+0900')),
            "requestId":link_info["payload"]["message"]["data"]["requestId"],
            "orderId":link_info["payload"]["message"]["data"]["orderId"],
            "senderMessageId":link_info["payload"]["message"]["messageId"],
            "senderChannelUrl":link_info["payload"]["message"]["chatRoomId"],
            "iosMinimumVersion":"3.45.0",
            "androidMinimumVersion":"3.45.0"
            }
        
        if link_password:
            receive_payload["passcode"]=link_password

        try:
            async with session.post("https://www.paypay.ne.jp/app/v2/p2p-api/acceptP2PSendMoneyLink", json=receive_payload, headers=base_headers, proxy=PROXY_URL) as response:
                response.raise_for_status()
                receive_data = await response.json()

                if receive_data.get("header", {}).get("resultCode") == "S0000":
                    return True
                else:
                    return False

        except aiohttp.ClientError as e:
            print(f"REVERR: {e}") #debug :) 
            return False
    
