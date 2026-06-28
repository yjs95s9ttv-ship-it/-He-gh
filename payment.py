"""
payment.py — PayPay / Kyash ローカル管理モジュール
設定は payment_config.json に保存されます（Supabase不要）
"""
import json, uuid, asyncio
from pathlib import Path

CONFIG_FILE = Path("payment_config.json")

def _load() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save(data: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════
#  PayPay
# ══════════════════════════════════════════════════════
class PayPayManager:
    def __init__(self):
        self._pending: dict | None = None   # {otp_id, phone, password, device_uuid}

    # ── 接続状態 ──────────────────────────────────────
    def status(self) -> dict:
        pp = _load().get("paypay", {})
        return {"connected": bool(pp.get("phone")), "phone": pp.get("phone", "")}

    def is_configured(self) -> bool:
        return self.status()["connected"]

    # ── ログイン開始（電話番号 + パスワード → OTP送信） ──
    async def start_login(self, phone: str, password: str) -> str:
        import paypayu
        device_uuid = _load().get("paypay", {}).get("device_uuid") or str(uuid.uuid4()).upper()
        result = await asyncio.to_thread(paypayu.login, phone, password, device_uuid)
        if result.get("response_type") == "ErrorResponse":
            raise Exception(result.get("error_description", "ログイン失敗"))
        otp_id = result.get("otp_reference_id")
        if not otp_id:
            raise Exception("OTP ID を取得できませんでした")
        self._pending = {"otp_id": otp_id, "phone": phone, "password": password, "device_uuid": device_uuid}
        return otp_id

    # ── OTP 認証 ──────────────────────────────────────
    async def verify_otp(self, otp: str) -> bool:
        import paypayu
        if not self._pending:
            raise Exception("先に /setup_paypay を実行してください")
        result = await asyncio.to_thread(
            paypayu.verify_otp,
            self._pending["otp_id"], otp, self._pending["device_uuid"]
        )
        if result.get("response_type") == "ErrorResponse":
            raise Exception(result.get("error_description", "OTP 認証失敗"))
        cfg = _load()
        cfg["paypay"] = {
            "phone": self._pending["phone"],
            "password": self._pending["password"],
            "device_uuid": self._pending["device_uuid"],
        }
        _save(cfg)
        self._pending = None
        return True

    # ── 送金リンクを受け取り ──────────────────────────
    async def claim(self, link: str) -> int:
        """送金リンクを受け取り、受取金額（円）を返す"""
        import paypayu
        pp = _load().get("paypay", {})
        if not pp:
            raise Exception("PayPay が設定されていません")
        result = await asyncio.to_thread(paypayu.claim, link, pp["device_uuid"])
        if result.get("response_type") == "ErrorResponse":
            raise Exception(result.get("error_description", "受取失敗"))
        try:
            amount = (
                result["payload"]["pendingPaymentInfo"]
                      ["pendingPaymentTransactionSummary"]
                      ["totalAmount"]["amount"]
            )
            return int(amount)
        except (KeyError, TypeError):
            return 0


# ══════════════════════════════════════════════════════
#  Kyash
# ══════════════════════════════════════════════════════
class KyashManager:
    def __init__(self):
        self._inst = None

    # ── 接続状態 ──────────────────────────────────────
    def status(self) -> dict:
        ky = _load().get("kyash", {})
        return {"connected": bool(ky.get("email")), "email": ky.get("email", "")}

    def is_configured(self) -> bool:
        return self.status()["connected"]

    # ── ログイン ──────────────────────────────────────
    async def login(self, email: str, password: str) -> bool:
        try:
            from Kyasher import Kyash
        except ImportError:
            from kyasher.main import Kyash
        k = Kyash()
        await asyncio.to_thread(k.login, email, password)
        cfg = _load()
        cfg["kyash"] = {"email": email, "password": password}
        _save(cfg)
        self._inst = k
        return True

    # ── インスタンス取得（必要なら再ログイン） ────────
    def _get(self):
        if self._inst:
            return self._inst
        try:
            from Kyasher import Kyash
        except ImportError:
            from kyasher.main import Kyash
        ky = _load().get("kyash", {})
        if not ky:
            raise Exception("Kyash が設定されていません")
        k = Kyash()
        k.login(ky["email"], ky["password"])
        self._inst = k
        return k

    # ── 受け取りリンク作成 ────────────────────────────
    async def create_link(self, amount: int) -> tuple[str, str]:
        """(url, link_id) を返す"""
        k = await asyncio.to_thread(self._get)
        result = await asyncio.to_thread(k.create_send_link, amount)
        url = result.get("url") or result.get("link") or ""
        link_id = result.get("id") or result.get("link_id") or ""
        return url, str(link_id)

    # ── 入金確認 ──────────────────────────────────────
    async def check_paid(self, link_id: str) -> bool:
        k = await asyncio.to_thread(self._get)
        try:
            result = await asyncio.to_thread(k.get_send_link_detail, link_id)
            return result.get("status") in ("completed", "COMPLETED") or result.get("isCompleted") is True
        except Exception:
            return False


# ── シングルトン ──────────────────────────────────────
paypay_mgr = PayPayManager()
kyash_mgr  = KyashManager()
