import json
import os
import re
import uuid

import discord
from discord import app_commands, ui
from discord.ext import commands

import paypayu
from utils import is_allowed

PAYPAY_DATA_FILE = "paypay_data.json"
VENDING_DATA_FILE = "vending_data.json"
PAYPAY_LINK_PATTERN = re.compile(r"https://pay\.paypay\.ne\.jp/[A-Za-z0-9]+")

PAYMENT_LABELS = {
    "paypay_money": "PayPayマネー",
    "paypay_money_light": "PayPayマネーライト",
    "paypay_cash": "PayPayキャッシュ",
    "kyash": "Kyash",
}


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


def get_paypay_entry(user_id: int | str):
    paypay_data = load_paypay_data()
    entry = paypay_data.get(str(user_id))
    if not entry:
        return None
    return ensure_paypay_defaults(entry)


def upsert_paypay_entry(user_id: int | str, entry: dict):
    paypay_data = load_paypay_data()
    paypay_data[str(user_id)] = ensure_paypay_defaults(entry)
    save_paypay_data(paypay_data)


def append_paypay_history(user_id: int | str, action: str, **payload):
    paypay_data = load_paypay_data()
    user_id_str = str(user_id)
    entry = ensure_paypay_defaults(paypay_data.get(user_id_str, {}))
    history = entry.setdefault("dm_history", [])
    history.insert(0, {
        "action": action,
        "at": discord.utils.utcnow().isoformat(),
        **payload,
    })
    entry["dm_history"] = history[:20]
    paypay_data[user_id_str] = entry
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


def parse_balance_summary(balance_response: dict) -> dict:
    payload = balance_response.get("payload", {})
    summary = {
        "total": get_amount_by_paths(payload, [
            ("totalBalance", "amount"),
            ("walletBalance", "amount"),
            ("balance", "amount"),
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
    return summary


def payment_label(method: str) -> str:
    return PAYMENT_LABELS.get(method, method.upper())


class PayPayModal(ui.Modal, title="PayPay OTP認証"):
    def __init__(self, phone, password, uuid_value, otpid, otp_pre=None):
        super().__init__(timeout=300)
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
            user_id_str = str(interaction.user.id)
            current = get_paypay_entry(user_id_str) or {}
            current.update({
                "phone": self.phone,
                "password": self.password,
                "uuid": self.uuid,
                "access_token": otp_result.get("access_token"),
                "refresh_token": otp_result.get("refresh_token"),
            })
            upsert_paypay_entry(user_id_str, current)

            vending_data = load_vending_data()
            updated_count = 0
            for vm_data in vending_data.values():
                if (
                    str(vm_data.get("owner_id")) == user_id_str
                    and vm_data.get("paypay_id") is None
                ):
                    vm_data["paypay_id"] = user_id_str
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

    def _registered_entry_or_raise(self, user_id: int | str):
        entry = get_paypay_entry(user_id)
        if not entry:
            raise ValueError("PayPayアカウントが登録されていません。先に `/paypayログイン` を実行してください。")
        return entry

    async def _require_token_entry(self, user_id: int | str):
        entry = self._registered_entry_or_raise(user_id)
        if not entry.get("access_token"):
            raise ValueError("アクセストークンが保存されていません。`/paypayログイン` を再実行してください。")
        return entry

    async def _accept_link_for_entry(self, entry: dict, link: str, passcode: str | None = None):
        access_token = entry.get("access_token")
        uuid_value = entry.get("uuid")
        if access_token and uuid_value:
            try:
                result = await paypayu.accept_link(access_token, uuid_value, link, passcode)
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
        paypay_data = load_paypay_data()
        user_id_str = str(interaction.user.id)
        if user_id_str not in paypay_data:
            embed = discord.Embed(
                title=command_name,
                description="PayPayアカウントは登録されていません。",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        del paypay_data[user_id_str]
        save_paypay_data(paypay_data)

        vending_data = load_vending_data()
        for vm_data in vending_data.values():
            if vm_data.get("paypay_id") == user_id_str:
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
        entry = get_paypay_entry(message.author.id)
        if not entry or not entry.get("auto_receive"):
            return
        try:
            result = await self._accept_link_for_entry(entry, link)
            success = result is True or result.get("header", {}).get("resultCode") == "S0000"
            if not success:
                return
            append_paypay_history(
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
            embed = discord.Embed(
                title="PayPayログインエラー",
                description="```ログイン情報とパスワードが一致していません。\n情報を正しく入力してください。```",
                color=0xff3333
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        modal = PayPayModal(
            phone,
            password,
            set_uuid,
            result.get("otp_reference_id"),
            result.get("otp_prefix"),
        )
        await interaction.response.send_modal(modal)

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
            entry = await self._require_token_entry(interaction.user.id)
            result = await paypayu.get_balance(entry["access_token"], entry["uuid"])
            if result.get("header", {}).get("resultCode") != "S0000":
                raise ValueError(result.get("header", {}).get("resultMessage", "残高取得に失敗しました。"))
            summary = parse_balance_summary(result)
            embed = discord.Embed(title="PayPay残高", color=discord.Color.green())
            embed.add_field(name="合計", value=f"```{summary.get('total', '不明')}円```", inline=False)
            embed.add_field(name="PayPayマネー", value=f"```{summary.get('money', '不明')}円```", inline=True)
            embed.add_field(name="PayPayマネーライト", value=f"```{summary.get('money_light', '不明')}円```", inline=True)
            embed.add_field(name="PayPayキャッシュ", value=f"```{summary.get('cash', '不明')}円```", inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_defined",
        description="PayPayの利用可能額を表示します"
    )
    @is_allowed()
    async def paypay_defined(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = await self._require_token_entry(interaction.user.id)
            result = await paypayu.get_balance(entry["access_token"], entry["uuid"])
            if result.get("header", {}).get("resultCode") != "S0000":
                raise ValueError(result.get("header", {}).get("resultMessage", "利用可能額の取得に失敗しました。"))
            summary = parse_balance_summary(result)
            usable = sum(
                value for value in (
                    summary.get("money"),
                    summary.get("money_light"),
                    summary.get("cash"),
                )
                if isinstance(value, (int, float))
            )
            embed = discord.Embed(title="利用可能額", description=f"```{usable}円```", color=discord.Color.blurple())
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_claimlink",
        description="PayPayの請求リンクを表示します"
    )
    @is_allowed()
    async def paypay_claimlink(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = await self._require_token_entry(interaction.user.id)
            result = await paypayu.create_mycode(entry["access_token"], entry["uuid"])
            if result.get("header", {}).get("resultCode") != "S0000":
                raise ValueError(result.get("header", {}).get("resultMessage", "請求リンクの取得に失敗しました。"))
            payload = result.get("payload", {})
            link = payload.get("link") or payload.get("linkUrl") or payload.get("deeplink") or payload.get("codeUrl")
            append_paypay_history(interaction.user.id, "claimlink", link=link or "N/A")
            embed = discord.Embed(title="PayPay請求リンク", color=discord.Color.green())
            embed.description = link or "リンクURLを取得できませんでした。"
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_profile",
        description="PayPayのプロフィール情報を表示します"
    )
    @is_allowed()
    async def paypay_profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = await self._require_token_entry(interaction.user.id)
            result = await paypayu.get_profile(entry["access_token"], entry["uuid"])
            if result.get("header", {}).get("resultCode") != "S0000":
                raise ValueError(result.get("header", {}).get("resultMessage", "プロフィール取得に失敗しました。"))
            payload = result.get("payload", {})
            embed = discord.Embed(title="PayPayプロフィール", color=discord.Color.green())
            for label, key in (
                ("表示名", "displayName"),
                ("電話番号", "maskedPhoneNumber"),
                ("ユーザーID", "externalUserId"),
                ("アイコン", "iconImageUrl"),
            ):
                if payload.get(key):
                    embed.add_field(name=label, value=f"```{payload[key]}```", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_history",
        description="PayPayの支出入の履歴を表示します"
    )
    @is_allowed()
    @app_commands.describe(limit="表示件数")
    async def paypay_history(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20] = 10):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = await self._require_token_entry(interaction.user.id)
            result = await paypayu.get_history(entry["access_token"], entry["uuid"], limit)
            if result.get("header", {}).get("resultCode") != "S0000":
                raise ValueError(result.get("header", {}).get("resultMessage", "履歴取得に失敗しました。"))
            payload = result.get("payload", {})
            items = payload.get("histories") or payload.get("history") or payload.get("transactions") or []
            embed = discord.Embed(title="PayPay履歴", color=discord.Color.blue())
            if not items:
                embed.description = "履歴はありません。"
            for item in items[:limit]:
                title = item.get("title") or item.get("name") or item.get("type") or "履歴"
                amount = (
                    item.get("amount")
                    or item.get("amountInfo", {}).get("amount")
                    or item.get("totalAmount", {}).get("amount")
                    or "不明"
                )
                created_at = item.get("createdAt") or item.get("date") or item.get("transactionTime") or "日時不明"
                embed.add_field(
                    name=str(title),
                    value=f"```金額: {amount}円\n日時: {created_at}```",
                    inline=False
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_receive",
        description="PayPayの受け取りリンクから受け取りを行います"
    )
    @is_allowed()
    @app_commands.describe(link="PayPayリンク", passcode="リンクに設定されたパスコード")
    async def paypay_receive(self, interaction: discord.Interaction, link: str, passcode: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = self._registered_entry_or_raise(interaction.user.id)
            result = await self._accept_link_for_entry(entry, link, passcode)
            success = result is True or result.get("header", {}).get("resultCode") == "S0000"
            if not success:
                raise ValueError("受け取りに失敗しました。リンクまたはパスコードを確認してください。")
            append_paypay_history(interaction.user.id, "receive", link=link)
            embed = discord.Embed(title="受け取り完了", description="PayPayリンクの受け取りに成功しました。", color=discord.Color.green())
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_createlink",
        description="PayPayの送金リンクを作成します"
    )
    @is_allowed()
    @app_commands.describe(amount="金額", passcode="任意のパスコード")
    async def paypay_createlink(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500000], passcode: str | None = None):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = await self._require_token_entry(interaction.user.id)
            result = await paypayu.create_link(entry["access_token"], entry["uuid"], amount, passcode)
            if result.get("header", {}).get("resultCode") != "S0000":
                raise ValueError(result.get("header", {}).get("resultMessage", "送金リンクの作成に失敗しました。"))
            payload = result.get("payload", {})
            link = payload.get("link") or payload.get("linkUrl") or payload.get("pendingP2PInfo", {}).get("link")
            append_paypay_history(interaction.user.id, "createlink", link=link or "N/A", amount=amount)
            embed = discord.Embed(title="送金リンク作成", color=discord.Color.green())
            embed.add_field(name="金額", value=f"```{amount}円```", inline=False)
            embed.add_field(name="リンク", value=link or "取得失敗", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(
        name="paypay_dmlist",
        description="PayPayのDM一覧を表示します"
    )
    @is_allowed()
    async def paypay_dmlist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            entry = self._registered_entry_or_raise(interaction.user.id)
            history = entry.get("dm_history", [])
            embed = discord.Embed(title="PayPay操作履歴", color=discord.Color.blurple())
            if not history:
                embed.description = "履歴はありません。"
            for item in history[:10]:
                action = item.get("action", "unknown")
                amount = item.get("amount")
                link = item.get("link")
                at = item.get("at", "不明")
                lines = [f"日時: {at}"]
                if amount is not None:
                    lines.append(f"金額: {amount}円")
                if link:
                    lines.append(f"リンク: {link}")
                embed.add_field(
                    name=action,
                    value="```" + "\n".join(lines) + "```",
                    inline=False
                )
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
            entry = self._registered_entry_or_raise(interaction.user.id)
            entry["auto_receive"] = enabled
            upsert_paypay_entry(interaction.user.id, entry)
            status = "有効" if enabled else "無効"
            await interaction.followup.send(f"✅ 自動受け取りを{status}にしました。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PaypayCog(bot))
