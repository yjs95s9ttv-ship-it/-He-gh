import asyncio
import json
import os
import re
import uuid

import discord
from discord import app_commands, ui
from discord.ext import commands

import paypay_ops
import paypayu
from utils import is_allowed

PAYPAY_DATA_FILE = "paypay_data.json"
VENDING_DATA_FILE = "vending_data.json"
PAYPAY_LINK_PATTERN = re.compile(r"https://pay\.paypay\.ne\.jp/[A-Za-z0-9]+")

def load_vending_data():
    if os.path.exists(VENDING_DATA_FILE):
        try:
            with open(VENDING_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error: {VENDING_DATA_FILE} のJSON形式が不正です。")
            return {}
    return {}


def save_vending_data(data):
    with open(VENDING_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_paypay_data():
    if os.path.exists(PAYPAY_DATA_FILE):
        with open(PAYPAY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_paypay_data(data):
    with open(PAYPAY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def ensure_paypay_defaults(data: dict) -> dict:
    data.setdefault("auto_receive", False)
    data.setdefault("dm_history", [])
    return data


def _paypay_key(guild_id: int | str, user_id: int | str) -> str:
    """PayPayデータのキーを生成する。必ずguild_id:user_idのペアで管理する。"""
    return f"{guild_id}:{user_id}"


def get_paypay_entry(guild_id: int | str, user_id: int | str):
    paypay_data = load_paypay_data()
    key = _paypay_key(guild_id, user_id)
    entry = paypay_data.get(key)
    if not entry:
        return None
    return ensure_paypay_defaults(entry)


def upsert_paypay_entry(guild_id: int | str, user_id: int | str, entry: dict):
    paypay_data = load_paypay_data()
    key = _paypay_key(guild_id, user_id)
    paypay_data[key] = ensure_paypay_defaults(entry)
    save_paypay_data(paypay_data)


def append_paypay_history(guild_id: int | str, user_id: int | str, action: str, **payload):
    paypay_data = load_paypay_data()
    key = _paypay_key(guild_id, user_id)
    entry = ensure_paypay_defaults(paypay_data.get(key, {}))
    history = entry.setdefault("dm_history", [])
    history.insert(0, {
        "action": action,
        "at": discord.utils.utcnow().isoformat(),
        **payload,
    })
    entry["dm_history"] = history[:20]
    paypay_data[key] = entry
    save_paypay_data(paypay_data)


def extract_paypay_link(text: str) -> str | None:
    match = PAYPAY_LINK_PATTERN.search(text or "")
    return match.group(0) if match else None


def find_first_amount(data, keys: tuple[str, ...]):
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys:
                if isinstance(value, dict) and "amount" in value:
                    return value.get("amount")
                if isinstance(value, (int, float)):
                    return value
            found = find_first_amount(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_first_amount(item, keys)
            if found is not None:
                return found
    return None


def get_amount_by_paths(data: dict, paths: list[tuple[str, ...]]):
    for path in paths:
        current = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if current is None:
            continue
        if isinstance(current, dict) and "amount" in current:
            return current["amount"]
        if isinstance(current, (int, float)):
            return current
    return None


def _normalize_balance_label(value) -> str:
    text = str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return text


def _extract_amount_from_balance_node(node: dict):
    return get_amount_by_paths(node, [
        ("amount",),
        ("balance", "amount"),
        ("usableBalance", "amount"),
        ("availableBalance", "amount"),
        ("totalAmount", "amount"),
        ("value", "amount"),
    ])


def _collect_balance_breakdown(data) -> dict:
    aliases = {
        "money": {
            "paypaymoney",
            "money",
            "moneybalance",
            "paypay_money",
            "paypaymoneybalance",
        },
        "money_light": {
            "paypaymoneylight",
            "moneylight",
            "moneylite",
            "moneylightbalance",
            "moneylitebalance",
            "paypay_money_light",
            "paypaymoneylightbalance",
        },
        "cash": {
            "paypaycash",
            "cash",
            "cashback",
            "cashbackbalance",
            "bonus",
            "bonusbalance",
            "bonuslite",
            "bonuslitebalance",
            "paypay_cash",
            "points",
        },
    }
    found = {}

    def visit(node):
        if isinstance(node, dict):
            labels = {
                _normalize_balance_label(node.get("paymentMethodType")),
                _normalize_balance_label(node.get("paymentMethod")),
                _normalize_balance_label(node.get("type")),
                _normalize_balance_label(node.get("kind")),
                _normalize_balance_label(node.get("name")),
                _normalize_balance_label(node.get("label")),
                _normalize_balance_label(node.get("title")),
                _normalize_balance_label(node.get("balanceType")),
            }
            amount = _extract_amount_from_balance_node(node)
            if amount is not None:
                for key, candidates in aliases.items():
                    if key in found:
                        continue
                    if any(label in candidates for label in labels if label):
                        found[key] = amount
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(data)
    return found


def parse_balance_summary(balance_response: dict) -> dict:
    payload = balance_response.get("payload", {})
    summary = {
        "total": get_amount_by_paths(payload, [
            ("totalBalance", "amount"),
            ("walletBalance", "amount"),
            ("balance", "amount"),
            ("usableBalance", "amount"),
        ]),
        "money": get_amount_by_paths(payload, [
            ("moneyBalance", "amount"),
            ("money", "amount"),
        ]),
        "money_light": get_amount_by_paths(payload, [
            ("moneyLiteBalance", "amount"),
            ("moneyLightBalance", "amount"),
            ("moneyLite", "amount"),
        ]),
        "cash": get_amount_by_paths(payload, [
            ("bonusLiteBalance", "amount"),
            ("cashbackBalance", "amount"),
            ("bonusBalance", "amount"),
        ]),
    }
    if summary["total"] is None:
        summary["total"] = find_first_amount(payload, ("totalBalance", "walletBalance", "balance"))
    if summary["money"] is None:
        summary["money"] = find_first_amount(payload, ("moneyBalance", "money"))
    if summary["money_light"] is None:
        summary["money_light"] = find_first_amount(payload, ("moneyLiteBalance", "moneyLightBalance", "moneyLite"))
    if summary["cash"] is None:
        summary["cash"] = find_first_amount(payload, ("bonusLiteBalance", "cashbackBalance", "bonusBalance"))
    breakdown = _collect_balance_breakdown(payload)
    for key in ("money", "money_light", "cash"):
        if summary[key] is None:
            summary[key] = breakdown.get(key)
    return summary


def format_amount_yen(value) -> str:
    return f"{value}円" if isinstance(value, (int, float)) else "不明"
class PayPayModal(ui.Modal, title="PayPay OTP認証"):
    def __init__(self, guild_id, phone, password, uuid_value, otpid, otp_pre=None):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.phone = phone
        self.password = password
        self.uuid = uuid_value
        self.otpid = otpid
        self.otp_pre = otp_pre

    otp_input = ui.TextInput(
        label="ワンタイムパスワード",
        placeholder="SMSに届いた4桁の認証コードを入力",
        min_length=4,
        max_length=4,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        otp_result = await paypayu.login_otp_raw(
            self.uuid,
            self.otp_input.value,
            self.otpid,
            self.otp_pre
        )

        if otp_result.get("response_type") != "ErrorResponse":
            guild_id = self.guild_id
            user_id = interaction.user.id
            current = get_paypay_entry(guild_id, user_id) or {}
            current.update({
                "phone": self.phone,
                "password": self.password,
                "uuid": otp_result.get("client_uuid") or self.uuid,
                "client_uuid": otp_result.get("client_uuid") or self.uuid,
                "device_uuid": otp_result.get("device_uuid") or self.uuid,
                "access_token": otp_result.get("access_token"),
                "refresh_token": otp_result.get("refresh_token"),
            })
            upsert_paypay_entry(guild_id, user_id, current)

            # 同じguild内の自分の自販機にだけpaypay_idを紐付ける
            paypay_key = _paypay_key(guild_id, user_id)
            vending_data = load_vending_data()
            updated_count = 0
            for vm_data in vending_data.values():
                if (
                    str(vm_data.get("owner_id")) == str(user_id)
                    and str(vm_data.get("guild_id")) == str(guild_id)
                    and vm_data.get("paypay_id") is None
                ):
                    vm_data["paypay_id"] = paypay_key
                    updated_count += 1

            if updated_count > 0:
                save_vending_data(vending_data)

            embed = discord.Embed(
                title="PayPay登録完了",
                description="PayPayアカウント情報の登録が完了しました。",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="PayPayログインエラー",
            description=otp_result.get("error_description", "OTPコードが正しくありません。"),
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


class PaypayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not os.path.exists(PAYPAY_DATA_FILE):
            save_paypay_data({})

    def _registered_entry_or_raise(self, guild_id: int | str, user_id: int | str):
        entry = get_paypay_entry(guild_id, user_id)
        if not entry:
            raise ValueError("PayPayアカウントが登録されていません。先に `/paypayログイン` を実行してください。")
        return entry

    async def _require_token_entry(self, guild_id: int | str, user_id: int | str):
        entry = self._registered_entry_or_raise(guild_id, user_id)
        if not entry.get("access_token"):
            raise ValueError("アクセストークンが保存されていません。`/paypayログイン` を再実行してください。")
        return entry

    async def _require_ops_token_entry(self, guild_id: int | str, user_id: int | str):
        entry = get_paypay_entry(guild_id, user_id) or {}
        if not entry.get("op_access_token"):
            raise ValueError("操作系アクセストークンが保存されていません。`/paypay操作ログイン` を実行してください。")
        if not entry.get("op_client_uuid") or not entry.get("op_device_uuid"):
            raise ValueError("操作系端末情報が不足しています。`/paypay操作ログイン` を再実行してください。")
        return entry

    def _entry_uuid(self, entry: dict) -> str:
        return entry.get("client_uuid") or entry.get("uuid")

    def _entry_device_uuid(self, entry: dict) -> str | None:
        return entry.get("device_uuid") or None

    def _result_message(self, result: dict, default: str) -> str:
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
        return header_message or default

    def _is_revoked_result(self, result: dict) -> bool:
        message = (result.get("header", {}).get("resultMessage") or "").lower()
        return "accesstoken is revoked" in message or "session refresh request because of accesstoken is revoked" in message

    def _clear_saved_tokens(self, guild_id: int | str, user_id: int | str):
        entry = get_paypay_entry(guild_id, user_id)
        if not entry:
            return
        changed = False
        for key in ("access_token", "refresh_token"):
            if entry.pop(key, None) is not None:
                changed = True
        if changed:
            upsert_paypay_entry(guild_id, user_id, entry)

    def _clear_saved_ops_tokens(self, guild_id: int | str, user_id: int | str):
        entry = get_paypay_entry(guild_id, user_id)
        if not entry:
            return
        changed = False
        for key in ("op_access_token", "op_refresh_token", "op_login_state_id"):
            if entry.pop(key, None) is not None:
                changed = True
        if changed:
            upsert_paypay_entry(guild_id, user_id, entry)

    async def _run_token_api(self, guild_id: int | str, user_id: int | str, api_call, default_error: str):
        entry = await self._require_token_entry(guild_id, user_id)
        result = await api_call(entry["access_token"], self._entry_uuid(entry))
        if self._is_revoked_result(result):
            self._clear_saved_tokens(guild_id, user_id)
            raise ValueError("PayPayのセッションが切れています。`/paypayログイン` を再実行してください。")
        if result.get("header", {}).get("resultCode") != "S0000":
            raise ValueError(self._result_message(result, default_error))
        return entry, result

    async def _run_ops_token_api(self, guild_id: int | str, user_id: int | str, api_call, default_error: str):
        entry = await self._require_ops_token_entry(guild_id, user_id)
        result = await asyncio.to_thread(
            api_call,
            entry["op_access_token"],
            entry["op_client_uuid"],
            entry["op_device_uuid"],
        )
        result_code = result.get("header", {}).get("resultCode")
        if result_code in {"S0001", "S1003"} or self._is_revoked_result(result):
            refresh_token = entry.get("op_refresh_token")
            if not refresh_token:
                self._clear_saved_ops_tokens(guild_id, user_id)
                raise ValueError("PayPay操作用のセッションが切れています。`/paypay操作ログイン` を再実行してください。")
            try:
                refreshed = await asyncio.to_thread(
                    paypay_ops.refresh_access_token,
                    refresh_token,
                    entry["op_client_uuid"],
                    entry["op_device_uuid"],
                    entry.get("op_access_token"),
                )
                payload = refreshed.get("payload", {})
                entry["op_access_token"] = payload.get("accessToken")
                entry["op_refresh_token"] = payload.get("refreshToken")
                upsert_paypay_entry(guild_id, user_id, entry)
                result = await asyncio.to_thread(
                    api_call,
                    entry["op_access_token"],
                    entry["op_client_uuid"],
                    entry["op_device_uuid"],
                )
                result_code = result.get("header", {}).get("resultCode")
            except Exception:
                self._clear_saved_ops_tokens(guild_id, user_id)
                raise ValueError("PayPay操作用のセッションが切れています。`/paypay操作ログイン` を再実行してください。")
        if result_code != "S0000":
            raise ValueError(self._result_message(result, default_error))
        return entry, result

    async def _ensure_legacy_send_link_entry(self, guild_id: int | str, user_id: int | str, *, force_relogin: bool = False) -> dict:
        entry = self._registered_entry_or_raise(guild_id, user_id)
        access_token = entry.get("access_token")
        uuid_value = self._entry_uuid(entry)
        if access_token and uuid_value and not force_relogin:
            return entry

        phone = entry.get("phone")
        password = entry.get("password")
        if not phone or not password:
            raise ValueError("旧送金リンクへの切り替えに必要な電話番号またはパスワードが保存されていません。")

        login_uuid = str(uuid.uuid4()) if force_relogin else (uuid_value or str(uuid.uuid4()))
        result = await paypayu.login(phone, password, login_uuid)
        if result.get("access_token"):
            entry.update({
                "phone": phone,
                "password": password,
                "uuid": result.get("client_uuid") or login_uuid,
                "client_uuid": result.get("client_uuid") or login_uuid,
                "device_uuid": result.get("device_uuid") or login_uuid,
                "access_token": result.get("access_token"),
                "refresh_token": result.get("refresh_token"),
            })
            upsert_paypay_entry(guild_id, user_id, entry)
            return entry

        if result.get("otp_reference_id"):
            raise ValueError("旧送金リンクへ切り替えるには `/paypayログイン` が必要です。")

        raise ValueError(
            result.get("error_description")
            or result.get("header", {}).get("resultMessage")
            or "旧送金リンクへの切り替えに失敗しました。"
        )

    async def _accept_link_for_entry(self, entry: dict, link: str, passcode: str | None = None):
        access_token = entry.get("access_token")
        uuid_value = self._entry_uuid(entry)
        device_uuid = self._entry_device_uuid(entry)
        if access_token and uuid_value:
            try:
                result = await paypayu.accept_link(access_token, uuid_value, link, passcode, device_uuid)
                if result.get("header", {}).get("resultCode") == "S0000":
                    return result
            except Exception:
                pass
        return await paypayu.link_rev(
            link,
            entry["phone"],
            entry["password"],
            entry["uuid"],
            passcode
        )

    async def _signout_user(self, interaction: discord.Interaction, *, command_name: str):
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        paypay_data = load_paypay_data()
        key = _paypay_key(guild_id, user_id)
        if key not in paypay_data:
            embed = discord.Embed(
                title=command_name,
                description="PayPayアカウントは登録されていません。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        del paypay_data[key]
        save_paypay_data(paypay_data)

        # 同じguildの自分の自販機のpaypay_idだけNullに戻す
        vending_data = load_vending_data()
        for vm_data in vending_data.values():
            if (
                vm_data.get("paypay_id") == key
                and str(vm_data.get("guild_id")) == str(guild_id)
            ):
                vm_data["paypay_id"] = None
        save_vending_data(vending_data)

        embed = discord.Embed(
            title=f"{command_name}完了",
            description="PayPayアカウント情報を削除しました。",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        link = extract_paypay_link(message.content)
        if not link:
            return
        if not message.guild:
            return
        entry = get_paypay_entry(message.guild.id, message.author.id)
        if not entry or not entry.get("auto_receive"):
            return
        try:
            result = await self._accept_link_for_entry(entry, link)
            success = result is True or result.get("header", {}).get("resultCode") == "S0000"
            if not success:
                return
            append_paypay_history(
                message.guild.id,
                message.author.id,
                "auto_receive",
                link=link,
            )
            try:
                await message.add_reaction("✅")
            except Exception:
                pass
        except Exception:
            pass

    @app_commands.command(
        name="paypayログイン",
        description="PayPayアカウントにログインします"
    )
    @is_allowed()
    @app_commands.describe(phone="電話番号", password="パスワード")
    async def paypay_register(
        self,
        interaction: discord.Interaction,
        phone: str,
        password: str
    ):
        set_uuid = str(uuid.uuid4())
        result = await paypayu.login(phone, password, set_uuid)

        if result.get("response_type") == "ErrorResponse":
            message = (
                result.get("error_description")
                or result.get("header", {}).get("resultMessage")
                or "ログインに失敗しました。時間を置いて再度お試しください。"
            )
            embed = discord.Embed(
                title="PayPayログインエラー",
                description=f"```{message}```",
                color=0xff3333
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if result.get("access_token"):
            guild_id = interaction.guild_id
            user_id = interaction.user.id
            current = get_paypay_entry(guild_id, user_id) or {}
            current.update({
                "phone": phone,
                "password": password,
                "uuid": result.get("client_uuid") or set_uuid,
                "client_uuid": result.get("client_uuid") or set_uuid,
                "device_uuid": result.get("device_uuid") or set_uuid,
                "access_token": result.get("access_token"),
                "refresh_token": result.get("refresh_token"),
            })
            upsert_paypay_entry(guild_id, user_id, current)
            embed = discord.Embed(
                title="PayPay登録完了",
                description="PayPayアカウント情報の登録が完了しました。",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not result.get("otp_reference_id"):
            embed = discord.Embed(
                title="PayPayログインエラー",
                description="```ログイン処理を開始できませんでした。時間を置いて再度お試しください。```",
                color=0xff3333
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        modal = PayPayModal(
            interaction.guild_id,
            phone,
            password,
            set_uuid,
            result.get("otp_reference_id"),
            result.get("otp_prefix"),
        )
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="paypay操作ログイン",
        description="PayPay操作系専用のログインを行います"
    )
    @is_allowed()
    @app_commands.describe(
        phone="電話番号。初回のみ必須",
        password="パスワード。初回のみ必須",
        otl_url="2段階認証で開いたURL。確認時のみ入力"
    )
    async def paypay_ops_login(
        self,
        interaction: discord.Interaction,
        phone: str | None = None,
        password: str | None = None,
        otl_url: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        current = get_paypay_entry(guild_id, user_id) or {}

        if otl_url:
            state_id = current.get("op_login_state_id")
            if not state_id:
                await interaction.followup.send(
                    "❌ 進行中の操作系ログインがありません。先に電話番号とパスワード付きで `/paypay操作ログイン` を実行してください。",
                    ephemeral=True,
                )
                return
            try:
                result = await asyncio.to_thread(paypay_ops.complete_login, state_id, otl_url)
                current.pop("op_login_state_id", None)
                current.update({
                    "op_access_token": result.get("access_token"),
                    "op_refresh_token": result.get("refresh_token"),
                    "op_client_uuid": result.get("client_uuid"),
                    "op_device_uuid": result.get("device_uuid"),
                })
                upsert_paypay_entry(guild_id, user_id, current)
                embed = discord.Embed(
                    title="PayPay操作ログイン完了",
                    description="操作系専用ログインが完了しました。`/paypay_balance` が利用できます。",
                    color=discord.Color.green(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        if not phone or not password:
            await interaction.followup.send(
                "❌ 初回は電話番号とパスワードが必要です。2段階認証の続きだけ行う場合は `otl_url` を指定してください。",
                ephemeral=True,
            )
            return

        try:
            result = await asyncio.to_thread(
                paypay_ops.start_login,
                phone,
                password,
                current.get("op_client_uuid"),
                current.get("op_device_uuid"),
            )
        except paypay_ops.PayPayOpsLoginError as e:
            if "Device UUID" in str(e):
                try:
                    result = await asyncio.to_thread(
                        paypay_ops.start_login,
                        phone,
                        password,
                        None,
                        None,
                    )
                except Exception as e2:
                    await interaction.followup.send(f"❌ {e2}", ephemeral=True)
                    return
            else:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
                return
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        if result.get("status") == "OK":
            current.update({
                "phone": phone,
                "password": password,
                "op_access_token": result.get("access_token"),
                "op_refresh_token": result.get("refresh_token"),
                "op_client_uuid": result.get("client_uuid"),
                "op_device_uuid": result.get("device_uuid"),
            })
            current.pop("op_login_state_id", None)
            upsert_paypay_entry(guild_id, user_id, current)
            embed = discord.Embed(
                title="PayPay操作ログイン完了",
                description="操作系専用ログインが完了しました。`/paypay_balance` が利用できます。",
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        current["op_login_state_id"] = result.get("state_id")
        current["phone"] = phone
        current["password"] = password
        current["op_client_uuid"] = result.get("client_uuid")
        current["op_device_uuid"] = result.get("device_uuid")
        upsert_paypay_entry(guild_id, user_id, current)
        embed = discord.Embed(
            title="PayPay操作ログイン続行",
            description=(
                "2段階認証が必要です。\n"
                "PayPay側で届いた認証URLを開いたあと、"
                "`https://www.paypay.ne.jp/portal/oauth2/l?id=...` を `otl_url` に入れて "
                "もう一度 `/paypay操作ログイン` を実行してください。"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="paypayログアウト",
        description="PayPayアカウントをログアウトします"
    )
    @is_allowed()
    async def paypay_logout(self, interaction: discord.Interaction):
        await self._signout_user(interaction, command_name="PayPayログアウト")

    @app_commands.command(
        name="paypay_signout",
        description="登録したPayPayアカウントからサインアウトします"
    )
    @is_allowed()
    async def paypay_signout(self, interaction: discord.Interaction):
        await self._signout_user(interaction, command_name="PayPayサインアウト")

    @app_commands.command(
        name="paypay_balance",
        description="PayPayの残高を確認します"
    )
    @is_allowed()
    async def paypay_balance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            _, result = await self._run_ops_token_api(
                interaction.guild_id,
                interaction.user.id,
                paypay_ops.get_balance,
                "PayPay残高を取得できませんでした。"
            )
            summary = parse_balance_summary(result)
            if any(summary.get(key) is None for key in ("money", "money_light", "cash")):
                try:
                    _, methods_result = await self._run_ops_token_api(
                        interaction.guild_id,
                        interaction.user.id,
                        paypay_ops.get_payment_method_list,
                        "支払い方法一覧を取得できませんでした。"
                    )
                    method_summary = parse_balance_summary(methods_result)
                    for key in ("money", "money_light", "cash"):
                        if summary.get(key) is None and method_summary.get(key) is not None:
                            summary[key] = method_summary.get(key)
                except Exception:
                    pass
            embed = discord.Embed(title="PayPay残高", color=discord.Color.green())
            embed.add_field(name="合計", value=f"```{format_amount_yen(summary.get('total'))}```", inline=False)
            embed.add_field(name="PayPayマネー", value=f"```{format_amount_yen(summary.get('money'))}```", inline=True)
            embed.add_field(name="PayPayマネーライト", value=f"```{format_amount_yen(summary.get('money_light'))}```", inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except Exception:
            await interaction.followup.send("❌ PayPay残高を取得できませんでした。", ephemeral=True)

    @app_commands.command(
        name="paypay_claimlink",
        description="PayPayの請求リンクを表示します"
    )
    @is_allowed()
    async def paypay_claimlink(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            _, result = await self._run_ops_token_api(
                interaction.guild_id,
                interaction.user.id,
                paypay_ops.create_mycode,
                "請求リンクの取得に失敗しました。"
            )
            payload = result.get("payload", {})
            link = (
                payload.get("link")
                or payload.get("linkUrl")
                or payload.get("deeplink")
                or payload.get("codeUrl")
                or payload.get("p2pCode")
                or payload.get("pendingP2PInfo", {}).get("link")
            )
            append_paypay_history(interaction.guild_id, interaction.user.id, "claimlink", link=link or "N/A")
            embed = discord.Embed(title="PayPay請求リンク", color=discord.Color.green())
            embed.description = link or "リンクURLを取得できませんでした。"
            await interaction.followup.send(embed=embed)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except Exception:
            await interaction.followup.send("❌ 請求リンクを取得できませんでした。", ephemeral=True)

    @app_commands.command(
        name="paypay_profile",
        description="PayPayのプロフィール情報を表示します"
    )
    @is_allowed()
    async def paypay_profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            _, result = await self._run_ops_token_api(
                interaction.guild_id,
                interaction.user.id,
                paypay_ops.get_profile,
                "プロフィール取得に失敗しました。"
            )
            payload = result.get("payload", {})
            profile = payload.get("userProfile") or payload.get("profile") or payload.get("displayInfo") or payload
            embed = discord.Embed(title="PayPayプロフィール", color=discord.Color.green())
            for label, key in (
                ("表示名", profile.get("nickName") or profile.get("displayName") or profile.get("name")),
                ("電話番号", profile.get("maskedPhoneNumber") or profile.get("phoneNumber")),
                ("ユーザーID", profile.get("externalUserId") or profile.get("userId") or profile.get("accountId")),
                ("アイコン", profile.get("avatarImageUrl") or profile.get("iconImageUrl")),
            ):
                if key:
                    embed.add_field(name=label, value=f"```{key}```", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except Exception:
            await interaction.followup.send("❌ プロフィールを取得できませんでした。", ephemeral=True)

    @app_commands.command(
        name="paypay_receive",
        description="PayPayの受け取りリンクから受け取りを行います"
    )
    @is_allowed()
    @app_commands.describe(link="PayPayリンク", passcode="リンクに設定されたパスコード")
    async def paypay_receive(self, interaction: discord.Interaction, link: str, passcode: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = self._registered_entry_or_raise(interaction.guild_id, interaction.user.id)
            result = await self._accept_link_for_entry(entry, link, passcode)
            success = result is True or result.get("header", {}).get("resultCode") == "S0000"
            if not success:
                raise ValueError("受け取りに失敗しました。リンクまたはパスコードを確認してください。")
            append_paypay_history(interaction.guild_id, interaction.user.id, "receive", link=link)
            embed = discord.Embed(title="受け取り完了", description="PayPayリンクの受け取りに成功しました。", color=discord.Color.green())
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_autoreceive",
        description="PayPayの自動受け取り設定を変更します"
    )
    @is_allowed()
    @app_commands.describe(enabled="有効にする場合はtrue、無効にする場合はfalse")
    async def paypay_autoreceive(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = self._registered_entry_or_raise(interaction.guild_id, interaction.user.id)
            entry["auto_receive"] = enabled
            upsert_paypay_entry(interaction.guild_id, interaction.user.id, entry)
            status = "有効" if enabled else "無効"
            await interaction.followup.send(f"✅ 自動受け取りを{status}にしました。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PaypayCog(bot))
