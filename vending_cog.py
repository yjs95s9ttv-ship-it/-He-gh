import discord
from discord import ui, app_commands
from discord.ext import commands
import aiohttp
import datetime
import json
import os
import math
import logging
import uuid
from pathlib import Path

# 外部ファイルの読み込み
import paypayu
from paypay_cog import get_paypay_entry, _paypay_key
from utils import is_allowed

# --- 設定・定数 ---
SETTINGS_FILE = "vending_settings.json"
SMM_API_URL = "https://smmjp.com/api/v2"


# ↓自分に合わせて好きに変更する↓
# ========================================================

# BOTオーナーのユーザーID
from utils import ADMIN_USER_IDS as _ADMIN_IDS
ADMIN_USER_ID = _ADMIN_IDS[0] if _ADMIN_IDS else 0

# APIキー
SMM_API_KEY = "ここを変える"

# 全サーバーの実績を送信する共通ログチャンネルID
GLOBAL_LOG_CHANNEL_ID = ここを変える

# オーナー専用コマンドの名前(変えなくてもOK)
ADMIN_LABEL = "《けーる専用》"

# embedのフロッパー(とりあえず自分の名前にすればOK)
BOT_FUROPA = "Createby:@keru_developer_"

# 実績ログのServerリンク(自鯖のリンク貼ればOK)
SUPPORT_SERVER = "https://discord.gg/3yHheMZkbk"

# SNSカテゴリーごとの絵文字(絵文字をコピーして貼り付け)
SNS_CONFIG = {
    "Instagram": {"emoji": "<:Instagram:1512467300782182610>"},     # インスタグラム
    "TikTok": {"emoji": "<:TikTok:1512466734471184424>"},        # Tiktok
    "X (Twitter)": {"emoji": "<:Twitter:1512466707514392626>"},   # Twitter
    "Threads": {"emoji": "<:threads:1512468081996202196>"},       # Threads
   "YouTube": {"emoji": "<:Youtube:1512466674337583124>"}         # YouTube
}

# =========================================================


# ログ設定
logger = logging.getLogger(__name__)
# --- 設定管理 ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "guilds" not in data:
                data["guilds"] = {}
            if "admin_stats" not in data:
                data["admin_stats"] = {"total_revenue": 0, "total_cost": 0}
            return data
    return {"guilds": {}, "services": {}, "maintenance": False, "admin_stats": {"total_revenue": 0, "total_cost": 0}}

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# --- 権限チェック関数 ---
def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.id == ADMIN_USER_ID
    return app_commands.check(predicate)

def is_guild_owner():
    async def predicate(interaction: discord.Interaction):
        if not interaction.guild: return False
        return interaction.user.id == interaction.guild.owner_id or interaction.user.id == ADMIN_USER_ID
    return app_commands.check(predicate)

# --- [UI] サーバーオーナー用報酬管理View ---
class RewardManagementView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @ui.button(label="残高確認", style=discord.ButtonStyle.primary, emoji="💰")
    async def check_balance(self, interaction: discord.Interaction, button: ui.Button):
        settings = load_settings()
        guild_id = str(interaction.guild.id)
        data = settings.get("guilds", {}).get(guild_id, {"balance": 0, "total_sales": 0})
        
        balance = data.get("balance", 0)
        total_sales = data.get("total_sales", 0)

        emb = discord.Embed(title="💳 サーバー報酬残高", color=0x5865F2)
        emb.add_field(name="現在の未出金報酬", value=f"### `¥{balance:,}`", inline=False)
        emb.add_field(name="累計売上額 (当サーバー)", value=f"¥{total_sales:,}", inline=True)
        emb.add_field(name="出金条件", value="1,000円から申請可能", inline=True)
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @ui.button(label="出金申請", style=discord.ButtonStyle.danger, emoji="💸")
    async def withdraw_request(self, interaction: discord.Interaction, button: ui.Button):
        settings = load_settings()
        guild_id = str(interaction.guild.id)
        data = settings.get("guilds", {}).get(guild_id, {"balance": 0})
        balance = data.get("balance", 0)

        if balance < 1000:
            return await interaction.response.send_message(f"❌ 出金申請には最低 `¥1,000` 必要です。\n(現在の残高: ¥{balance:,})", ephemeral=True)

        admin = await self.bot.fetch_user(ADMIN_USER_ID)
        if admin:
            req_id = str(uuid.uuid4())[:8].upper()
            w_emb = discord.Embed(title="📢 【出金申請】届きました", color=0xffd700, timestamp=datetime.datetime.now())
            w_emb.add_field(name="申請元サーバー", value=f"{interaction.guild.name}\n(ID: `{guild_id}`)", inline=True)
            w_emb.add_field(name="申請ユーザー", value=f"{interaction.user.mention}\n({interaction.user})", inline=True)
            w_emb.add_field(name="申請額", value=f"## `¥{balance:,}`", inline=False)
            w_emb.add_field(name="照合コード", value=f"`{req_id}`", inline=True)
            w_emb.set_footer(text="送金完了後、管理コマンド /v_reward_reset で残高をリセットしてください。")

            try:
                await admin.send(embed=w_emb)
                await interaction.response.send_message(f"✅ 管理者へ `¥{balance:,}` の出金申請を送信しました。\n(照合コード: {req_id})", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ 管理者のDMが閉じられているため、申請を送信できませんでした。", ephemeral=True)

# --- [UI ステップ3] PayPayリンク入力Modal ---
class PayPayInputModal(ui.Modal, title="最終決済"):
    def __init__(self, service_data, quantity, total_price, target_url):
        super().__init__()
        self.info = service_data
        self.quantity = quantity
        self.total_price = total_price
        self.target_url = target_url
        
        self.paylink = ui.TextInput(
            label=f"PayPay送金リンクを入力 (¥{total_price:,})",
            placeholder="https://pay.paypay.ne.jp/...",
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.paylink)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # そのサーバーのオーナーのPayPayアカウントを取得
        guild = interaction.guild
        if not guild:
            return await interaction.followup.send("❌ サーバー外からは使用できません。", ephemeral=True)

        guild_owner_id = guild.owner_id
        owner_entry = get_paypay_entry(guild.id, guild_owner_id)
        if not owner_entry:
            return await interaction.followup.send(
                "❌ 決済システムエラー: このサーバーのオーナーがPayPayを登録していません。\nオーナーに `/フォロ爆paypayログイン` の実行を依頼してください。",
                ephemeral=True
            )

        link_info = await paypayu.check_link(self.paylink.value)
        if not link_info:
            return await interaction.followup.send("❌ このPayPayリンクは無効、またはすでに受け取り済みです。", ephemeral=True)

        try:
            actual_amount = int(link_info['payload']['pendingP2PInfo']['amount'])
            if actual_amount != self.total_price:
                return await interaction.followup.send(
                    f"❌ 金額が一致しません。\n請求額: ¥{self.total_price:,}\n送金額: ¥{actual_amount:,}\n正しい金額のリンクを再入力してください。",
                    ephemeral=True
                )
        except (KeyError, TypeError):
            return await interaction.followup.send("❌ PayPayリンクの解析に失敗しました。", ephemeral=True)

        success = await paypayu.link_rev(
            self.paylink.value,
            owner_entry['phone'],
            owner_entry['password'],
            owner_entry.get('client_uuid') or owner_entry.get('uuid')
        )
        
        if success is True:
            params = {
                'key': SMM_API_KEY, 
                'action': 'add', 
                'service': self.info['id'], 
                'link': self.target_url, 
                'quantity': self.quantity
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(SMM_API_URL, data=params, timeout=15) as r:
                        res = await r.json(content_type=None)
            except Exception as e:
                return await interaction.followup.send(f"❌ API接続エラー: 決済は完了しましたがパネルへの注文に失敗しました。\nエラー: {e}", ephemeral=True)
            
            if "order" in res:
                settings = load_settings()
                guild_name = interaction.guild.name if interaction.guild else "DM/不明"
                if interaction.guild:
                    gid = str(interaction.guild.id)
                    if gid not in settings["guilds"]:
                        settings["guilds"][gid] = {"log_channel_id": None, "balance": 0, "total_sales": 0}
                    
                    reward = math.floor(self.total_price * 0.2)
                    settings["guilds"][gid]["balance"] = settings["guilds"][gid].get("balance", 0) + reward
                    settings["guilds"][gid]["total_sales"] = settings["guilds"][gid].get("total_sales", 0) + self.total_price
                
                actual_cost = math.ceil((self.info['price'] * self.quantity) / 1000)
                settings["admin_stats"]["total_revenue"] += self.total_price
                settings["admin_stats"]["total_cost"] += actual_cost
                save_settings(settings)

                receipt = discord.Embed(title="✅ ご注文ありがとうございます", color=0x2ecc71, timestamp=datetime.datetime.now())
                receipt.add_field(name="注文ID (OrderID)", value=f"`{res['order']}`", inline=False)
                receipt.add_field(name="購入商品", value=self.info['name'], inline=True)
                receipt.add_field(name="注文数量", value=f"{self.quantity:,} 件", inline=True)
                receipt.add_field(name="決済金額", value=f"¥{self.total_price:,}", inline=True)
                receipt.add_field(name="拡散対象URL", value=self.target_url, inline=False)
                receipt.set_footer(text="＊減少補充ボタンから補充可能 保証期間は購入から30日間")

                try:
                    await interaction.user.send(embed=receipt)
                    await interaction.followup.send("✅ 注文が完了しました。DMにレシートを送信しました。", ephemeral=True)
                except discord.Forbidden:
                    await interaction.followup.send("✅ 注文完了！(DMが閉じられているため、ここにレシートを表示します)", embed=receipt, ephemeral=True)

                # --- ログ共通項目 ---
                l_emb = discord.Embed(title="購入ログ", color=0x00ff00, timestamp=datetime.datetime.now())
                l_emb.add_field(name="購入サーバー", value=f"**{guild_name}**", inline=False)
                l_emb.add_field(name="購入者", value=f"{interaction.user.mention}")
                l_emb.add_field(name="内容", value=f"{self.info['name']} (¥{self.total_price:,})")
                l_emb.add_field(name="数量", value=f"{self.quantity:,} 件")
                l_emb.add_field(name="OrderID", value=f"`{res['order']}`")

                # 各サーバーの個別ログ送信
                if interaction.guild:
                    log_channel_id = settings.get("guilds", {}).get(str(interaction.guild.id), {}).get("log_channel_id")
                    if log_channel_id:
                        log_chan = interaction.client.get_channel(int(log_channel_id))
                        if log_chan:
                            try: await log_chan.send(
                                     embed=l_emb,
                                     view=LogButtonView())
                            except: pass
                # 全サーバーの実績を管理用チャンネルに送信
                global_chan = interaction.client.get_channel(GLOBAL_LOG_CHANNEL_ID)
                if global_chan:
                    try: await global_chan.send(
                             embed=l_emb,
                             view=LogButtonView())
                    except: pass

            else:
                await interaction.followup.send(f"❌ パネルエラー: {res.get('error', '不明なエラー')}\n決済は完了しています。運営までお問い合わせください。", ephemeral=True)
        else:
            await interaction.followup.send("❌ PayPay決済失敗: リンクが無効、または期限切れです。", ephemeral=True)

            
class LogButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        # ① サポートサーバー
        self.add_item(discord.ui.Button(
            label="🌐 サポートサーバー",
            url=SUPPORT_SERVER,
            style=discord.ButtonStyle.link
        ))

# --- [UI ステップ2] 購入確認画面 ---
class ConfirmPurchaseView(ui.View):
    def __init__(self, service_data, quantity, total_price, target_url):
        super().__init__(timeout=300)
        self.info = service_data
        self.quantity = quantity
        self.total_price = total_price
        self.target_url = target_url

    @ui.button(label="購入を確定して決済へ", style=discord.ButtonStyle.green, emoji="💳")
    async def confirm_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(PayPayInputModal(self.info, self.quantity, self.total_price, self.target_url))

# --- [UI ステップ1] 注文数量・URL入力Modal ---
class PurchaseInfoModal(ui.Modal, title="注文情報の入力"):
    def __init__(self, service_data):
        super().__init__()
        self.info = service_data
        min_val = service_data.get('min', 100)
        max_val = service_data.get('max', 1000000)
        
        self.qty = ui.TextInput(
            label=f"注文数量 ({min_val:,} 〜 {max_val:,})", 
            default=str(min_val),
            style=discord.TextStyle.short,
            required=True
        )
        self.url = ui.TextInput(
            label="拡散先URL", 
            placeholder="対象のSNSリンクを入力してください", 
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.qty)
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            quantity = int(self.qty.value)
            min_limit = self.info.get('min', 0)
            max_limit = self.info.get('max', 99999999)
            
            if quantity < min_limit:
                return await interaction.response.send_message(f"❌ 最小注文数は {min_limit:,} です。", ephemeral=True)
            if quantity > max_limit:
                return await interaction.response.send_message(f"❌ 最大注文数は {max_limit:,} です。", ephemeral=True)
            
            total_price = math.ceil((self.info['price'] * quantity) / 1000)
            
            confirm_emb = discord.Embed(title="🛒 購入内容の確認", color=0x3498db)
            confirm_emb.description = (
                f"以下の内容で注文を受け付けます。金額を確認してください。\n\n"
                f"**■ 商品名:** {self.info['name']}\n"
                f"**■ 注文数量:** {quantity:,} 件\n"
                f"**■ 拡散先URL:** {self.url.value}\n\n"
                f"### 合計金額: `¥{total_price:,}`"
            )
            confirm_emb.set_footer(text="内容に間違いがなければ、下のボタンを押して決済へお進みください。")
            
            await interaction.response.send_message(
                embed=confirm_emb, 
                view=ConfirmPurchaseView(self.info, quantity, total_price, self.url.value), 
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("❌ 数量は半角数字で入力してください。", ephemeral=True)

# --- [UI ステップ 1.5] カテゴリ内の商品を選択するセレクトメニュー ---
class ServiceSelect(ui.Select):
    def __init__(self, category, services):
        # 指定されたカテゴリの商品のみを表示
        self.category_services = {k: v for k, v in services.items() if v["category"] == category}
        options = [
            discord.SelectOption(
                label=s["name"], 
                value=k, 
                description=f"¥{s['price']/1000}/単価 (最小{s['min']:,}〜)"
            ) for k, s in self.category_services.items()
        ]
        super().__init__(placeholder=f"{category} の商品を選択してください", options=options)

    async def callback(self, interaction: discord.Interaction):
        service_key = self.values[0]
        service_data = self.category_services[service_key]
        await interaction.response.send_modal(PurchaseInfoModal(service_data))

# --- [UI] 減少補充用Modal ---
class RefillModal(ui.Modal, title="♻️ 減少補充の申請"):
    oid = ui.TextInput(label="注文ID (OrderID)", placeholder="例: 12345", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        params = {'key': SMM_API_KEY, 'action': 'refill', 'order': self.oid.value}
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(SMM_API_URL, data=params) as r:
                    res = await r.json(content_type=None)
            if "refill" in res:
                await interaction.followup.send(f"✅ 補充申請を受け付けました。(RefillID: {res['refill']})", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ エラー: {res.get('error', 'この注文は補充対象外か、まだ補充できません。')}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 接続エラーが発生しました: {e}", ephemeral=True)

# --- [UI] メインパネルView ---
class SNSSelectView(ui.View):
    def __init__(self, services, current_page=0, show_controls=True):
        super().__init__(timeout=None)
        self.all_services = services
        self.current_page = current_page
        self.show_controls = show_controls
        
        self.guaranteed_services = {}
        self.non_guaranteed_services = {}
        
        for k, s in services.items():
            if "保証" in s["name"] or "HQ" in s["name"]:
                self.guaranteed_services[k] = s
            else:
                self.non_guaranteed_services[k] = s
        
        self.pages_data = [
            {"title": " 減少保証あり (高品質メニュー)", "data": self.guaranteed_services, "color": 0x2ecc71},
            {"title": " 減少保証なし (格安メニュー)", "data": self.non_guaranteed_services, "color": 0xe74c3c}
        ]
        
        if self.show_controls:
            self._build_interface()

    def _build_interface(self):
        self.clear_items()
        current_page_info = self.pages_data[self.current_page]
        current_data = current_page_info["data"]

        # そのページに存在する商品からカテゴリ一覧を作成 (保証あり/なしの同期)
        available_cats = sorted(list(set(s["category"] for s in current_data.values())))
        if available_cats:
            options = [
                discord.SelectOption(
                    label=cat, 
                    value=cat, 
                    emoji=SNS_CONFIG.get(cat, {"emoji": "📱"})["emoji"]
                ) for cat in available_cats
            ]
            sm = ui.Select(
                custom_id=f"sns_vending_select_p{self.current_page}", 
                placeholder=f"商品カテゴリを選択してください", 
                options=options
            )
            sm.callback = self.sns_callback
            self.add_item(sm)

        btn_status = ui.Button(
            label="状況確認", 
            style=discord.ButtonStyle.secondary, 
            custom_id=f"sns_vending_status_p{self.current_page}"
        )
        btn_status.callback = self.status_callback
        self.add_item(btn_status)

        btn_refill = ui.Button(
            label="減少補充", 
            style=discord.ButtonStyle.primary, 
            custom_id=f"sns_vending_refill_p{self.current_page}"
        )
        btn_refill.callback = self.refill_callback
        self.add_item(btn_refill)

    def create_embed(self):
        page_info = self.pages_data[self.current_page]
        embed = discord.Embed(title=page_info["title"], color=page_info["color"])
        embed.description = "PayPay決済対応 | 24時間稼働中\n"
        
        content = ""
        current_data = page_info["data"]
        categories = sorted(list(set(s["category"] for s in current_data.values())))
        
        for cat in categories:
            conf = SNS_CONFIG.get(cat, {"emoji": "📱"})
            content += f"\n{conf['emoji']} **{cat}**\n"
            for k, s in current_data.items():
                if s["category"] == cat:
                    content += f"┣ {s['name']}: `¥{s['price']/1000}/単価` \n"
        
        embed.description += content if content else "\n現在、このカテゴリに商品はございません。"
        embed.set_footer(text=BOT_FUROPA)
        return embed

    async def sns_callback(self, interaction: discord.Interaction):
        selected_cat = interaction.data['values'][0]
        # 現在のページのデータのみを引き継ぐ
        current_data = self.pages_data[self.current_page]["data"]
        view = ui.View(timeout=120)
        view.add_item(ServiceSelect(selected_cat, current_data))
        await interaction.response.send_message(content=f" **{selected_cat}** の商品を選択してください：", view=view, ephemeral=True)

    async def status_callback(self, interaction: discord.Interaction):
        class StatusModal(ui.Modal, title="📊 注文状況の照会"):
            oid = ui.TextInput(label="注文ID (OrderID)", placeholder="例: 12345")
            async def on_submit(self, inter: discord.Interaction):
                await inter.response.defer(ephemeral=True)
                params = {'key': SMM_API_KEY, 'action': 'status', 'order': self.oid.value}
                try:
                    async with aiohttp.ClientSession() as sess:
                        async with sess.post(SMM_API_URL, data=params) as r:
                            res = await r.json(content_type=None)
                    if "status" in res:
                        s_map = {"Pending": "⏳ 待機中", "In progress": "🚀 進行中", "Completed": "✅ 完了", "Partial": "⚠️ 一部完了", "Canceled": "❌ キャンセル"}
                        st = s_map.get(res['status'], res['status'])
                        await inter.followup.send(f"📋 **OrderID: {self.oid.value}**\n現在のステータス: **{st}**\n残り数量: {res.get('remains', '0')}", ephemeral=True)
                    else:
                        await inter.followup.send(f" 注文が見つかりませんでした。IDを確認してください。", ephemeral=True)
                except Exception as e:
                    await inter.followup.send(f" 接続エラーが発生しました: {e}", ephemeral=True)
        await interaction.response.send_modal(StatusModal())

    async def refill_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RefillModal())

# --- [Cog] コマンド統合 ---
class VendingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        settings = load_settings()
        services = settings.get("services", {})

        bot.add_view(SNSSelectView(services,current_page=0,show_controls=True))

        bot.add_view(SNSSelectView(services,current_page=1,show_controls=True))

        bot.add_view(LogButtonView())

    @app_commands.command(name="フォロ爆商品追加", description=f"{ADMIN_LABEL}自販機に商品を追加します")
    @app_commands.choices(category=[app_commands.Choice(name=k, value=k) for k in SNS_CONFIG.keys()])
    @is_admin()
    async def add_service(self, interaction: discord.Interaction, category: app_commands.Choice[str], name: str, service_id: int, price: int, min_qty: int = 100, max_qty: int = 1000000):
        settings = load_settings()
        key = f"{category.value}_{service_id}"
        settings["services"][key] = {
            "category": category.value, "name": name, "id": service_id, "price": price, "min": min_qty, "max": max_qty
        }
        save_settings(settings)
        await interaction.response.send_message(f" `{category.value}` に `{name}` を登録しました。\n(ID: {service_id} / 最小:{min_qty:,} / 最大:{max_qty:,})", ephemeral=True)

    @app_commands.command(name="フォロ爆paypayログイン", description=f"{ADMIN_LABEL}PayPayにログインします（鯖主が自分の鯖で実行）")
    @is_guild_owner()
    async def paypay_login(self, interaction: discord.Interaction, phone: str, password: str):
        set_uuid = str(uuid.uuid4())
        result = await paypayu.login(phone, password, set_uuid)
        if result.get("response_type") == "ErrorResponse":
            embed = discord.Embed(title="PayPayログインエラー", description="```ログイン情報が一致しません。```", color=0xff3333)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if result.get("access_token"):
            # OTP不要で直接ログイン成功
            from paypay_cog import upsert_paypay_entry, get_paypay_entry
            current = get_paypay_entry(interaction.guild_id, interaction.user.id) or {}
            current.update({
                "phone": phone,
                "password": password,
                "uuid": result.get("client_uuid") or set_uuid,
                "client_uuid": result.get("client_uuid") or set_uuid,
                "device_uuid": result.get("device_uuid") or set_uuid,
                "access_token": result.get("access_token"),
                "refresh_token": result.get("refresh_token"),
            })
            upsert_paypay_entry(interaction.guild_id, interaction.user.id, current)
            embed = discord.Embed(title="PayPay登録完了", description="PayPayアカウント情報の登録が完了しました。", color=discord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not result.get("otp_reference_id"):
            embed = discord.Embed(title="PayPayログインエラー", description="```ログイン処理を開始できませんでした。```", color=0xff3333)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        from paypay_cog import PayPayModal as PPModal
        modal = PPModal(interaction.guild_id, phone, password, set_uuid, result.get("otp_reference_id"), result.get("otp_prefix"))
        await interaction.response.send_modal(modal)

    @app_commands.command(name="フォロ爆paypayログアウト", description=f"{ADMIN_LABEL}自分のPayPay情報を削除します")
    @is_guild_owner()
    async def paypay_logout(self, interaction: discord.Interaction):
        from paypay_cog import load_paypay_data, save_paypay_data, _paypay_key
        data = load_paypay_data()
        key = _paypay_key(interaction.guild_id, interaction.user.id)
        if key in data:
            del data[key]
            save_paypay_data(data)
            await interaction.response.send_message("✅ PayPay情報を削除しました。", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 登録情報がありません。", ephemeral=True)

    @app_commands.command(name="報酬リセット", description=f"{ADMIN_LABEL}報酬をリセットします")
    @is_admin()
    async def reward_reset(self, interaction: discord.Interaction, guild_id: str):
        settings = load_settings()
        if guild_id not in settings.get("guilds", {}):
            return await interaction.response.send_message(" データが見つかりません。", ephemeral=True)
        settings["guilds"][guild_id]["balance"] = 0
        save_settings(settings)
        await interaction.response.send_message(f" サーバー `{guild_id}` の報酬を0にリセットしました。", ephemeral=True)

    @app_commands.command(name="総合利益", description=f"{ADMIN_LABEL}システム全体の収支統計をDMに送信します")
    @is_admin()
    async def admin_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        settings = load_settings()
        stats = settings.get("admin_stats", {"total_revenue": 0, "total_cost": 0})
        total_rev = stats["total_revenue"]
        total_cost = stats["total_cost"]
        unpaid_rewards = sum(g.get("balance", 0) for g in settings.get("guilds", {}).values())
        
        emb = discord.Embed(title=" システム総合収支統計レポート", color=0x2ecc71, timestamp=datetime.datetime.now())
        emb.add_field(name=" 総売上", value=f"```json\n¥{total_rev:,}\n```", inline=False)
        
        sorted_guilds = sorted(settings.get("guilds", {}).items(), key=lambda x: x[1].get("total_sales", 0), reverse=True)[:50]
        rank_text = "".join([f"{i}位: ID `{gid}` | 売上 ¥{data.get('total_sales',0):,}\n" for i, (gid, data) in enumerate(sorted_guilds, 1)])
        if rank_text:
            emb.add_field(name=" サーバー別売上", value=f"```\n{rank_text}```", inline=False)

        try:
            await interaction.user.send(embed=emb)
            await interaction.followup.send(" 詳細レポートをDMに送信しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(embed=emb, ephemeral=True)

    @app_commands.command(name="フォロ爆自販機パネル設置", description="《鯖主用》自販機パネルを設置します")
    @is_guild_owner()
    async def panel(self, interaction: discord.Interaction):
        settings = load_settings()
        services = settings["services"]

        # 上段：高品質パネル
        view_top = SNSSelectView(services, current_page=0, show_controls=True)
        embed_top = view_top.create_embed()

        # 下段：格安パネル
        view_bottom = SNSSelectView(services, current_page=1, show_controls=True)
        embed_bottom = view_bottom.create_embed()

        await interaction.response.send_message(embed=embed_top, view=view_top)
        
        await interaction.channel.send(embed=embed_bottom, view=view_bottom)

    @app_commands.command(name="実績送信チャンネル", description="《鯖主用》実績送信先チャンネルを設定します")
    @is_guild_owner()
    async def log_set(self, interaction: discord.Interaction, channel: discord.TextChannel):
        settings = load_settings()
        gid = str(interaction.guild.id)
        if gid not in settings["guilds"]: settings["guilds"][gid] = {"balance": 0, "total_sales": 0}
        settings["guilds"][gid]["log_channel_id"] = channel.id
        save_settings(settings)
        await interaction.response.send_message(f" 通知先を {channel.mention} に設定。", ephemeral=True)

    @app_commands.command(name="出金申請", description="《鯖主用》報酬確認と出金申請")
    @is_guild_owner()
    async def reward_panel(self, interaction: discord.Interaction):
        emb = discord.Embed(title=" サーバー報酬システム", description="利益の20%が報酬として貯まります。1,000円から申請可能。", color=0x9b59b6)
        await interaction.response.send_message(embed=emb, view=RewardManagementView(self.bot), ephemeral=True)

    @add_service.error
    @log_set.error
    @panel.error
    @paypay_login.error
    @reward_reset.error
    @reward_panel.error
    async def generic_error_handler(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(" 実行権限がありません。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(VendingCog(bot))
