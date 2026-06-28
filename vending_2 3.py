# vending.py (Part 1 - First half)
from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import sys
import os
import uuid
import io
from utils import is_allowed
import paypayu
import random
import requests
from bs4 import BeautifulSoup
from typing import NamedTuple, Optional
import datetime


VENDING_DATA_FILE = "vending_data.json"
PAYPAY_DATA_FILE = "paypay_data.json"
KYASH_DATA_FILE = "kyash_data.json"
STOCK_DIR_BASE = "stock_files"
STOCK_NOTIFICATION_DATA_FILE = "stock_notification_data.json"
COUPON_DATA_FILE = "coupon_data.json"
ROLE_ASSIGNMENT_DATA_FILE = "role_assignment_data.json"

STOCK_DIR = "stock_files"
os.makedirs(STOCK_DIR, exist_ok=True)

stock_file_path = os.path.join(STOCK_DIR, f"{uuid.uuid4()}.txt")

def load_json(file_path: str) -> dict:
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_json(file_path: str, data: dict) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_paypay_data() -> dict:
    if os.path.exists(PAYPAY_DATA_FILE):
        with open(PAYPAY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_paypay_data(data: dict) -> None:
    with open(PAYPAY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_kyash_data() -> dict:
    if os.path.exists(KYASH_DATA_FILE):
        with open(KYASH_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_kyash_data(data: dict) -> None:
    with open(KYASH_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_stock_notification_data() -> dict:
    if os.path.exists(STOCK_NOTIFICATION_DATA_FILE):
        with open(STOCK_NOTIFICATION_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_stock_notification_data(data: dict) -> None:
    with open(STOCK_NOTIFICATION_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_coupon_data() -> dict:
    if os.path.exists(COUPON_DATA_FILE):
        with open(COUPON_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_coupon_data(data: dict) -> None:
    with open(COUPON_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_role_assignment_data() -> dict:
    if os.path.exists(ROLE_ASSIGNMENT_DATA_FILE):
        with open(ROLE_ASSIGNMENT_DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_role_assignment_data(data: dict) -> None:
    with open(ROLE_ASSIGNMENT_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

PAYMENT_METHOD_LABELS = {
    "paypay_money": "PayPayマネー",
    "paypay_money_light": "PayPayマネーライト",
    "kyash": "Kyash",
}


def generate_relink_password(length: int = 10) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(length))


def normalize_product_prices(product: dict) -> dict:
    legacy_paypay_price = product.get("price_paypay", product.get("price", 0))
    product.setdefault("price_paypay_money", legacy_paypay_price)
    product.setdefault("price_paypay_money_light", legacy_paypay_price)
    product.setdefault("price_kyash", 0)
    product.setdefault("price_paypay", product.get("price_paypay_money", legacy_paypay_price))
    return product


def get_product_price(product: dict, payment_method: str) -> int:
    normalized = normalize_product_prices(product)
    price_key = f"price_{payment_method}"
    return normalized.get(price_key, normalized.get("price", 0))


def payment_method_label(payment_method: str) -> str:
    return PAYMENT_METHOD_LABELS.get(payment_method, payment_method.upper())


def format_product_prices(product: dict) -> str:
    normalized = normalize_product_prices(product)
    return (
        "```"
        f"PayPayマネー: {normalized.get('price_paypay_money', 0)}円 | "
        f"PayPayマネーライト: {normalized.get('price_paypay_money_light', 0)}円 | "
        f"Kyash: {normalized.get('price_kyash', 0)}円"
        "```"
    )

# ==================== オートコンプリート関数 ====================

async def vending_machine_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    vending_data = load_json(VENDING_DATA_FILE)
    user_id_str = str(interaction.user.id)
    
    user_machines = []
    for vm_id, vm_data in vending_data.items():
        if isinstance(vm_data, dict) and vm_data.get("owner_id") == user_id_str:
            user_machines.append((vm_id, vm_data))

    return [
        app_commands.Choice(name=vm_data.get("name", "名称未設定"), value=vm_id)
        for vm_id, vm_data in user_machines
        if current.lower() in vm_data.get("name", "").lower()
    ]

async def coupon_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    coupon_data = load_coupon_data()
    user_id_str = str(interaction.user.id)
    
    user_coupons = [
        (coupon_code, coupon_info) for coupon_code, coupon_info in coupon_data.items()
        if coupon_info.get("owner_id") == user_id_str
    ]
    
    choices = []
    for coupon_code, coupon_info in user_coupons:
        if current.lower() in coupon_code.lower():
            discount = coupon_info.get("discount", 0)
            vending_machine_id = coupon_info.get("vending_machine_id", "")
            vending_data = load_json(VENDING_DATA_FILE)
            vm_name = vending_data.get(vending_machine_id, {}).get("name", "不明")
            choices.append(app_commands.Choice(
                name=f"{coupon_code} (-{discount}円) [{vm_name}]",
                value=coupon_code
            ))
    
    return choices[:25]

async def role_assignment_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    role_data = load_role_assignment_data()
    vending_data = load_json(VENDING_DATA_FILE)
    
    choices = []
    for vm_id, role_info in role_data.items():
        if role_info.get("guild_id") == interaction.guild.id:
            vm = vending_data.get(vm_id)
            if vm and vm.get("owner_id") == str(interaction.user.id):
                vm_name = vm.get("name", "不明な自販機")
                if current.lower() in vm_name.lower():
                    choices.append(app_commands.Choice(name=vm_name, value=vm_id))
    
    return choices[:25]

# ==================== エラーハンドリング ====================

async def handle_error(interaction: discord.Interaction, error: Exception, ephemeral: bool = True) -> None:
    """統一エラーハンドリング"""
    try:
        embed = discord.Embed(
            title="エラーが発生しました",
            description=f"```{str(error)}```",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Developer @m_shoppp")
        
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except:
        print(f"Error sending error message: {error}")

async def check_stock(interaction: discord.Interaction, products: list) -> None:
    embed = discord.Embed(
        title="在庫・販売数情報",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text="Developer @m_shoppp")

    if not products:
        embed.description = "この自販機には商品が登録されていません。"
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    for product in products:
        product_name = product.get("name", "不明")
        sales_count = product.get("sales_count", 0)
        
        if product.get("infinite_stock"):
            embed.add_field(
                name=f"{product_name}", 
                value=f"```在庫数: ∞個\n販売数: {sales_count}個```", 
                inline=False
            )
        else:
            stock_file = product.get("stock_file")
            
            if not stock_file:
                embed.add_field(
                    name=f"{product_name}", 
                    value=f"```在庫数: 不明\n販売数: {sales_count}個```", 
                    inline=False
                )
                continue
                
            try:
                with open(stock_file, "r", encoding="utf-8") as file:
                    lines = [line for line in file.readlines() if line.strip()]
                    stock_count = len(lines)
                    embed.add_field(
                        name=f"{product_name}", 
                        value=f"```在庫数: {stock_count}個\n販売数: {sales_count}個```", 
                        inline=False
                    )

            except FileNotFoundError:
                embed.add_field(
                    name=f"{product_name}", 
                    value=f"```在庫数: 0個\n販売数: {sales_count}個```", 
                    inline=False
                )
            except Exception as e:
                await handle_error(interaction, e)

    await interaction.followup.send(embed=embed, ephemeral=True)
    
class KyashError(Exception):
    pass

class KyashLinkInfo(NamedTuple):
    amount: int
    uuid: str

class Kyash:
    def __init__(self, client_uuid=None, installation_uuid=None, access_token=None, proxy=None):
        self.access_token = access_token
        self.proxy = proxy
        self.client_uuid = client_uuid or str(uuid.uuid4()).upper()
        self.installation_uuid = installation_uuid or str(uuid.uuid4()).upper()
        
        self.version = "11.8.1"
        self.headers = {
            "Host": "api.kyash.me",
            "Content-Type": "application/json",
            "X-Kyash-Client-Id": self.client_uuid,
            "Accept": "application/json",
            "X-Kyash-Device-Language": "ja",
            "X-Kyash-Client-Version": self.version,
            "X-Kyash-Device-Info": "iPhone 8, Version:16.7.5",
            "Accept-Language": "ja-jp",
            "X-Kyash-Date": str(round(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).timestamp())),
            "Accept-Encoding": "gzip, deflate, br",
            "User-Agent": "Kyash/2 CFNetwork/1240.0.4 Darwin/20.6.0",
            "X-Kyash-Installation-Id": self.installation_uuid,
            "X-Kyash-Os": "iOS",
            "Connection": "keep-alive"
        }
        
        if access_token:
            self.headers["X-Auth"] = access_token

    def get_profile(self):
        if not self.access_token:
            raise KyashError("まずはログインしてください")
        
        try:
            getprofile = requests.get("https://api.kyash.me/v1/me", headers=self.headers, proxies=self.proxy).json()
            if getprofile.get("code") != 200:
                raise KyashError(getprofile.get("error", {}).get("message", "プロフィール取得失敗"))
            
            data = getprofile.get("result", {}).get("data", {})
            
            class Profile(NamedTuple):
                username: str
                icon: str
                myouzi: str
                namae: str
                phone: str
                is_kyc: bool
                raw: dict
            
            return Profile(
                username=data.get("userName", ""),
                icon=data.get("imageUrl", ""),
                myouzi=data.get("lastNameReal", ""),
                namae=data.get("firstNameReal", ""),
                phone=data.get("phoneNumber", ""),
                is_kyc=data.get("kyc", False),
                raw=getprofile
            )
        except Exception as e:
            raise KyashError(f"プロフィール取得エラー: {str(e)}")

    def link_check(self, url: str):
        """URLからUUIDと金額を抽出"""
        if "https://kyash.me/payments/" not in url:
            url = "https://kyash.me/payments/" + url
        
        try:
            res = requests.get(url).text
            soup = BeautifulSoup(res, "html.parser")
            
            amount_element = soup.find(class_="amountText text_send")
            if not amount_element:
                raise KyashError("リンクが既に受取済みか、無効です。")
            
            amount = amount_element.text.replace("¥", "").replace(",", "")
            btn_element = soup.find(class_="btn_send")
            if not btn_element:
                raise KyashError("リンク情報が見つかりません。")
            
            link_uuid = btn_element.get("data-href-app", "").replace("kyash://claim/", "")
            
            return KyashLinkInfo(amount=int(amount), uuid=link_uuid)
        except KyashError:
            raise
        except Exception as e:
            raise KyashError(f"リンク解析失敗: {str(e)}")

    def link_receive(self, link_uuid: str):
        """抽出したUUIDを使って受取APIを叩く"""
        try:
            res = requests.put(
                f"https://api.kyash.me/v1/links/{link_uuid}/receive", 
                headers=self.headers,
                proxies=self.proxy
            ).json()
            
            if res.get("code") != 200:
                raise KyashError(res.get("error", {}).get("message", "受取に失敗しました"))
            
            return res
        except KyashError:
            raise
        except Exception as e:
            raise KyashError(f"受取処理エラー: {str(e)}")


# ==================== VendingMachineCog ====================

class VendingMachineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Cogロード時に永続化Viewを復元"""
        vending_data = load_json(VENDING_DATA_FILE)
        
        for vm_id in vending_data.keys():
            view = VendingMachineCog.VendingMachineView(vm_id, self.bot)
            self.bot.add_view(view)
        
        products_data = []
        for vm_data in vending_data.values():
            if isinstance(vm_data, dict):
                products_data.extend(vm_data.get("products", []))
        
        if products_data:
            stock_view = VendingMachineCog.ProductSelectViewForStock(products_data)
            self.bot.add_view(stock_view)
            
            withdraw_view = VendingMachineCog.WithdrawStockView(products_data, 1)
            self.bot.add_view(withdraw_view)
            
            content_view = VendingMachineCog.ContentView(products_data)
            self.bot.add_view(content_view)

    @app_commands.command(name="自販機作成", description="自販機を作成します")
    @is_allowed()
    @app_commands.describe(name="自販機の名前")
    async def vm_create(self, interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        vending_data = load_json(VENDING_DATA_FILE)
        new_vm_id = str(uuid.uuid4())
        relink_password = generate_relink_password()

        paypay_data = load_paypay_data()
        paypay_id = user_id if user_id in paypay_data else None

        kyash_data = load_kyash_data()
        kyash_id = user_id if user_id in kyash_data else None

        vending_data[new_vm_id] = {
            "name": name,
            "owner_id": user_id,
            "relink_password": relink_password,
            "paypay_id": paypay_id,
            "kyash_id": kyash_id,
            "log_channel_id": None,
            "private_log_channel_id": None,
            "products": []
        }
        save_json(VENDING_DATA_FILE, vending_data)

        msg_parts = [
            f"自販機「{name}」を作成しました。\n**自販機ID:** `{new_vm_id}`",
            f"**引き継ぎパスワード:** `{relink_password}`",
            "Discordアカウント変更時はこのIDとパスワードで引き継げます。必ずメモしておいてください。"
        ]
        
        if not paypay_id:
            msg_parts.append("PayPayアカウントが未登録です。`/paypayログイン` を実行してください。")
        if not kyash_id:
            msg_parts.append("Kyashアカウントが未登録です。`/kyash_login` を実行してください。")
        
        await interaction.response.send_message("\n".join(msg_parts), ephemeral=True)

    @app_commands.command(name="自販機引き継ぎ", description="Discordアカウント変更時に自販機を引き継ぎます")
    @is_allowed()
    @app_commands.describe(vending_machine_id="引き継ぐ自販機ID", password="自販機作成時に表示された引き継ぎパスワード")
    async def vm_relink(self, interaction: discord.Interaction, vending_machine_id: str, password: str):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or not isinstance(vm, dict):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        stored_password = vm.get("relink_password")
        if not stored_password:
            stored_password = generate_relink_password()
            vm["relink_password"] = stored_password
            save_json(VENDING_DATA_FILE, vending_data)
            return await interaction.response.send_message(
                "この自販機にはまだ引き継ぎパスワードが設定されていません。旧アカウントで一度内容を確認してから再度お試しください。",
                ephemeral=True
            )

        if stored_password != password:
            return await interaction.response.send_message("引き継ぎパスワードが正しくありません。", ephemeral=True)

        old_owner_id = str(vm.get("owner_id"))
        new_owner_id = str(interaction.user.id)
        if old_owner_id == new_owner_id:
            return await interaction.response.send_message("この自販機はすでに現在のアカウントに紐づいています。", ephemeral=True)

        moved_accounts = []
        paypay_data = load_paypay_data()
        if vm.get("paypay_id") == old_owner_id and old_owner_id in paypay_data:
            paypay_data.setdefault(new_owner_id, paypay_data[old_owner_id].copy())
            vm["paypay_id"] = new_owner_id
            save_paypay_data(paypay_data)
            moved_accounts.append("PayPay")

        kyash_data = load_kyash_data()
        if vm.get("kyash_id") == old_owner_id and old_owner_id in kyash_data:
            kyash_data.setdefault(new_owner_id, kyash_data[old_owner_id].copy())
            vm["kyash_id"] = new_owner_id
            save_kyash_data(kyash_data)
            moved_accounts.append("Kyash")

        vm["owner_id"] = new_owner_id
        vending_data[vending_machine_id] = vm
        save_json(VENDING_DATA_FILE, vending_data)

        coupon_data = load_coupon_data()
        coupon_updated = 0
        for coupon_info in coupon_data.values():
            if coupon_info.get("vending_machine_id") == vending_machine_id and coupon_info.get("owner_id") == old_owner_id:
                coupon_info["owner_id"] = new_owner_id
                coupon_updated += 1
        if coupon_updated:
            save_coupon_data(coupon_data)

        moved_text = " / ".join(moved_accounts) if moved_accounts else "なし"
        await interaction.response.send_message(
            f"自販機「{vm.get('name', '名称未設定')}」を現在のDiscordアカウントへ引き継ぎました。\n"
            f"移行した決済情報: `{moved_text}`",
            ephemeral=True
        )

    @app_commands.command(name="引き継ぎパスワード確認", description="自販機の引き継ぎパスワードを確認または再発行します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="対象の自販機", regenerate="trueで新しいパスワードに再発行します")
    async def vm_relink_password(self, interaction: discord.Interaction, vending_machine_id: str, regenerate: bool = False):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        if regenerate or not vm.get("relink_password"):
            vm["relink_password"] = generate_relink_password()
            save_json(VENDING_DATA_FILE, vending_data)

        await interaction.response.send_message(
            f"自販機「{vm.get('name', '名称未設定')}」の引き継ぎパスワードは `{vm['relink_password']}` です。",
            ephemeral=True
        )

    @app_commands.command(name="公開ログ設定", description="全サーバー共通の公開販売ログを送信するチャンネルを設定します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", channel="ログを集約するチャンネル")
    async def vm_set_log(self, interaction: discord.Interaction, vending_machine_id: str, channel: discord.TextChannel):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
        
        vm["log_channel_id"] = channel.id
        save_json(VENDING_DATA_FILE, vending_data)
        await interaction.response.send_message(f"自販機「{vm['name']}」のログチャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @app_commands.command(name="購入ログ設定", description="このサーバー内での購入ログを送信するチャンネルを設定します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", channel="このサーバー用のログチャンネル")
    async def vm_set_local_log(self, interaction: discord.Interaction, vending_machine_id: str, channel: discord.TextChannel):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
        
        if "server_logs" not in vm:
            vm["server_logs"] = {}
        
        vm["server_logs"][str(interaction.guild.id)] = channel.id
        
        save_json(VENDING_DATA_FILE, vending_data)
        await interaction.response.send_message(f"このサーバーでの購入ログチャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @app_commands.command(name="非公開ログ設定", description="非公開販売ログを送信するチャンネルを設定します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", channel="ログを送信するチャンネル")
    async def vm_set_private_log(self, interaction: discord.Interaction, vending_machine_id: str, channel: discord.TextChannel):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
        
        vm["private_log_channel_id"] = channel.id
        save_json(VENDING_DATA_FILE, vending_data)
        
        await interaction.response.send_message(f"自販機「{vm['name']}」の非公開ログチャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @app_commands.command(name="商品追加", description="指定した自販機に新しい商品を追加します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(
        vending_machine_id="商品を登録する自販機",
        name="商品名",
        description="商品説明（任意）",
        price_paypay_money="PayPayマネー価格",
        price_paypay_money_light="PayPayマネーライト価格",
        price_kyash="Kyash価格",
        emoji="商品絵文字"
    )
    async def vm_add_product(
        self, 
        interaction: discord.Interaction, 
        vending_machine_id: str, 
        name: str, 
        price_paypay_money: int,
        price_paypay_money_light: int,
        price_kyash: int,
        description: Optional[str] = None, 
        emoji: Optional[str] = None
    ):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        product_id = str(uuid.uuid4())
        stock_file_path = os.path.join(STOCK_DIR_BASE, f"{product_id}.txt")
        with open(stock_file_path, "w", encoding="utf-8") as f:
            pass

        new_product = {
            "product_id": product_id,
            "name": name,
            "description": description or "",
            "price_paypay": price_paypay_money,
            "price_paypay_money": price_paypay_money,
            "price_paypay_money_light": price_paypay_money_light,
            "price_kyash": price_kyash,
            "emoji": emoji,
            "stock_file": stock_file_path,
            "infinite_stock": False,
            "infinite_content": None,
            "sales_count": 0
        }
        vm["products"].append(new_product)
        save_json(VENDING_DATA_FILE, vending_data)
        await interaction.response.send_message(
            f"自販機「{vm['name']}」に商品「{name}」を追加しました。\n"
            f"PayPayマネー: {price_paypay_money}円 | "
            f"PayPayマネーライト: {price_paypay_money_light}円 | "
            f"Kyash: {price_kyash}円",
            ephemeral=True
        )

    @app_commands.command(name="在庫追加", description="商品の在庫を追加します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", stock_type="在庫タイプ", stock_file="在庫ファイル(txtのみ)")
    @app_commands.choices(stock_type=[
        app_commands.Choice(name="有限", value="finite"),
        app_commands.Choice(name="無限", value="infinite")
    ])
    async def vm_add_stock(self, interaction: discord.Interaction, vending_machine_id: str, stock_type: str, stock_file: Optional[discord.Attachment] = None):
        
        if stock_file and not stock_file.filename.endswith(".txt"):
            return await interaction.response.send_message("ファイル形式は.txtのみ対応しています。", ephemeral=True)

        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("在庫を追加できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.ProductSelectViewForStock(products, stock_file, stock_type)
        await interaction.response.send_message("在庫追加を行う商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="自販機設置", description="自販機パネルを設置します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(
        vending_machine_id="設置する自販機", 
        panel_title="パネルのタイトル",
        panel_description="パネルの説明文",
        panel_image="パネルの画像"
    )
    async def vm_setup(self, interaction: discord.Interaction, vending_machine_id: str, panel_title: Optional[str] = None, panel_description: Optional[str] = None, panel_image: Optional[discord.Attachment] = None):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm:
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        is_custom = any([panel_title, panel_description, panel_image])
        
        if is_custom:
            title = panel_title if panel_title else "自販機"
            description = panel_description if panel_description else "購入したい商品を下のメニューから選択してください。"
            embed = discord.Embed(title=title, description=description, color=discord.Color.green())
            
            if panel_image:
                embed.set_image(url=panel_image.url)
        else:
            embed = discord.Embed(title="自販機", description="購入したい商品を下のメニューから選択してください。", color=discord.Color.green())
        
        embed.set_footer(text="Developer @m_shoppp")
        
        products = vm.get("products", [])
        if products:
            for p in products:
                price_text = format_product_prices(p)
                product_description = p.get('description', '').strip()
                if product_description:
                    value = f"{product_description}\n{price_text}"
                else:
                    value = price_text
                embed.add_field(
                    name=f"{p['name']}", 
                    value=value, 
                    inline=False
                )
        else:
            if not is_custom:
                embed.description = "```現在、販売中の商品はありません。```"

        view = VendingMachineCog.VendingMachineView(vending_machine_id, self.bot)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="在庫引出", description="商品の在庫を引き出します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機", quantity="数量")
    async def vm_withdraw_stock(self, interaction: discord.Interaction, vending_machine_id: str, quantity: int):
        if quantity <= 0:
            return await interaction.response.send_message("引出数量は1以上で指定してください。", ephemeral=True)

        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("引出できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.WithdrawStockView(products, quantity)
        await interaction.response.send_message("在庫引出を行う商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="在庫内容確認", description="商品の在庫内容を確認します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機")
    async def vm_check_stock_content(self, interaction: discord.Interaction, vending_machine_id: str):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("内容を確認できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.ContentView(products)
        await interaction.response.send_message("在庫内容確認を行う商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="商品削除", description="自販機から商品を完全に削除します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機")
    async def vm_delete_product(self, interaction: discord.Interaction, vending_machine_id: str):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("削除できる商品がありません。", ephemeral=True)
        
        view = ui.View(timeout=None)
        view.add_item(VendingMachineCog.ProductSelectForDelete(products))
        
        await interaction.response.send_message("削除する商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="商品情報変更", description="商品の各情報を変更します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="自販機")
    async def vm_edit_product(self, interaction: discord.Interaction, vending_machine_id: str):
        vending_data = load_json(VENDING_DATA_FILE)
        vm = vending_data.get(vending_machine_id)
        if not vm or vm.get("owner_id") != str(interaction.user.id):
            return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)

        products = vm.get("products")
        if not products:
            return await interaction.response.send_message("情報を変更できる商品がありません。", ephemeral=True)
        
        view = VendingMachineCog.EditProductView(products, vending_machine_id)
        await interaction.response.send_message("情報を変更する商品を選択してください:", view=view, ephemeral=True)

    @app_commands.command(name="自販機削除", description="自販機を完全に削除します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="削除する自販機")
    async def vm_delete(self, interaction: discord.Interaction, vending_machine_id: str):
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)

            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
            
            vm_name = vm.get("name", "名称不明")
            
            view = VendingMachineCog.VendingMachineDeleteConfirmView(vending_machine_id, vm_name)
            
            embed = discord.Embed(
                title="自販機削除確認",
                description=f"本当に自販機「{vm_name}」を削除しますか？\n\n**この操作は取り消せません。**\n**すべての商品と在庫データも削除されます。**",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Developer @m_shoppp")
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)
    
    @app_commands.command(name="自販機パネル更新", description="自販機パネルを更新します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(
        vending_machine_id="更新する自販機", 
        message_link="更新するメッセージのリンク",
        panel_title="パネルのタイトル",
        panel_description="パネルの説明文",
        panel_image="パネルの画像"
    )
    async def vm_update(self, interaction: discord.Interaction, vending_machine_id: str, message_link: str, panel_title: Optional[str] = None, panel_description: Optional[str] = None, panel_image: Optional[discord.Attachment] = None):
        await interaction.response.defer(ephemeral=True)
        
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                embed = discord.Embed(
                    title="ERROR",
                    description="指定された自販機が見つかりません。",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Developer @m_shoppp")
                return await interaction.followup.send(embed=embed, ephemeral=True)
            
            try:
                link_parts = message_link.replace("https://discord.com/channels/", "").replace("https://discordapp.com/channels/", "")
                guild_id, channel_id, message_id = link_parts.split("/")
                
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    embed = discord.Embed(
                        title="ERROR",
                        description="指定されたチャンネルが見つかりません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @m_shoppp")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                message = await channel.fetch_message(int(message_id))
                if not message:
                    embed = discord.Embed(
                        title="ERROR",
                        description="指定されたメッセージが見つかりません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @m_shoppp")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                if message.author.id != self.bot.user.id:
                    embed = discord.Embed(
                        title="ERROR",
                        description="指定されたメッセージはBOTが送信したものではありません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @m_shoppp")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
            except (ValueError, IndexError):
                embed = discord.Embed(
                    title="ERROR",
                    description="メッセージリンクの形式が正しくありません。",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Developer @m_shoppp")
                return await interaction.followup.send(embed=embed, ephemeral=True)
            
            is_custom = any([panel_title, panel_description, panel_image])
            
            if is_custom:
                title = panel_title if panel_title else "自販機"
                description = panel_description if panel_description else "購入したい商品を下のメニューから選択してください。"
                embed = discord.Embed(title=title, description=description, color=discord.Color.green())
                
                if panel_image:
                    embed.set_image(url=panel_image.url)
            else:
                embed = discord.Embed(
                    title="自販機", 
                    description="購入したい商品を下のメニューから選択してください。", 
                    color=discord.Color.green()
                )
            
            embed.set_footer(text="Developer @m_shoppp")
            
            products = vm.get("products", [])
            if products:
                for p in products:
                    price_text = format_product_prices(p)
                    product_description = p.get('description', '').strip()
                    if product_description:
                        value = f"{product_description}\n{price_text}"
                    else:
                        value = price_text
                    embed.add_field(
                        name=f"{p['name']}", 
                        value=value, 
                        inline=False
                    )
            else:
                if not is_custom:
                    embed.description = "```現在、販売中の商品はありません。```"
            
            view = VendingMachineCog.VendingMachineView(vending_machine_id, self.bot)
            
            await message.edit(embed=embed, view=view)
            
            embed_success = discord.Embed(
                title="更新完了",
                description=f"自販機「{vm['name']}」のパネルを更新しました。",
                color=discord.Color.green()
            )
            embed_success.set_footer(text="Developer @m_shoppp")
            await interaction.followup.send(embed=embed_success, ephemeral=True)
            
        except Exception as e:
            await handle_error(interaction, e)

    # ==================== Inner Classes ====================

    class VendingMachineDeleteConfirmView(ui.View):
        def __init__(self, vending_machine_id: str, vm_name: str):
            super().__init__(timeout=300)
            self.vending_machine_id = vending_machine_id
            self.vm_name = vm_name

        @ui.button(label="削除する", style=discord.ButtonStyle.danger)
        async def confirm_delete(self, interaction: discord.Interaction, button: ui.Button):
            await interaction.response.defer(ephemeral=True)
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id)

                if not vm or vm.get("owner_id") != str(interaction.user.id):
                    return await interaction.followup.send("指定された自販機が見つかりません。", ephemeral=True)
                
                for product in vm.get("products", []):
                    stock_file_path = product.get("stock_file")
                    if stock_file_path and os.path.exists(stock_file_path):
                        try:
                            os.remove(stock_file_path)
                        except Exception:
                            pass

                del vending_data[self.vending_machine_id]
                save_json(VENDING_DATA_FILE, vending_data)

                embed = discord.Embed(
                    title="削除完了",
                    description=f"自販機「{self.vm_name}」を削除しました。",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="Developer @m_shoppp")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

        @ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
        async def cancel_delete(self, interaction: discord.Interaction, button: ui.Button):
            embed = discord.Embed(
                title="キャンセル",
                description="自販機削除をキャンセルしました。",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Developer @m_shoppp")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    class PaymentMethodSelect(ui.Select):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            self.vending_machine_id = vending_machine_id
            self.bot = bot
            options = [
                discord.SelectOption(label="PayPayマネー", value="paypay_money",  emoji="<:emoji_7:1487256597670531163>"),
                discord.SelectOption(label="PayPayマネーライト", value="paypay_money_light",  emoji="<:emoji_7:1487256597670531163>"),
                discord.SelectOption(label="Kyash", value="kyash",  emoji="<:emoji_6:1487256579530297425>"),
            ]
            super().__init__(
                placeholder="決済方法を選択してください",
                options=options,
                custom_id=f"payment_method_{vending_machine_id}"
            )

        async def callback(self, interaction: discord.Interaction):
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id, {})
                if not vm:
                    return await interaction.response.send_message("自販機が見つかりません。", ephemeral=True)
                
                embed = discord.Embed(
                    title="購入する商品を選択してください。",
                    color=discord.Color.green()
                )
                view = VendingMachineCog.ProductSelectView(
                    self.vending_machine_id, 
                    self.bot,
                    self.values[0]
                )
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

    class PaymentMethodView(ui.View):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.PaymentMethodSelect(vending_machine_id, bot))

    class CouponModal(ui.Modal, title="購入情報入力"):
        def __init__(self, vending_machine_id: str, product: dict, bot: commands.Bot, payment_method: str):
            super().__init__()
            self.vending_machine_id = vending_machine_id
            self.product = product
            self.bot = bot
            self.payment_method = payment_method
            
            self.quantity_input = ui.TextInput(
                label="購入数", 
                placeholder="1", 
                default="1",
                required=True, 
                max_length=5
            )
            self.add_item(self.quantity_input)
            
            self.coupon_input = ui.TextInput(
                label="クーポンコード", 
                placeholder="あればクーポンコードを入力", 
                required=False, 
                max_length=50
            )
            self.add_item(self.coupon_input)

        async def on_submit(self, interaction: discord.Interaction):
            try:
                if self.product.get('infinite_stock'):
                    quantity = 1
                else:
                    quantity = int(self.quantity_input.value)
                    if quantity <= 0: 
                        return await interaction.response.send_message("購入数は1以上で入力してください。", ephemeral=True)
                    
            except ValueError:
                return await interaction.response.send_message("購入数には整数を入力してください。", ephemeral=True)

            coupon_code = self.coupon_input.value.strip() if self.coupon_input.value else None
            
            discount = 0
            if coupon_code:
                coupon_data = load_coupon_data()
                if coupon_code in coupon_data:
                    coupon_info = coupon_data[coupon_code]
                    if coupon_info.get("vending_machine_id") == self.vending_machine_id:
                        discount = coupon_info.get("discount", 0)
                    else:
                        return await interaction.response.send_message("このクーポンコードはこの自販機では使用できません。", ephemeral=True)
                else:
                    return await interaction.response.send_message("無効なクーポンコードです。", ephemeral=True)
            
            product_price = get_product_price(self.product, self.payment_method)
            
            base_price = product_price * quantity
            total_discount = discount * quantity
            final_price = max(0, base_price - total_discount)
            
            embed = discord.Embed(
                title="購入確認",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="商品名", value=f"```{self.product['name']}```", inline=False)
            
            if self.product.get('infinite_stock'):
                embed.add_field(name="個数", value=f"```1個```", inline=False)
            else:
                embed.add_field(name="個数", value=f"```{quantity}個```", inline=False)
            
            embed.add_field(
                name="決済方法",
                value=f"```{payment_method_label(self.payment_method)}```",
                inline=False
            )
            
            if discount > 0:
                embed.add_field(
                    name="金額",
                    value=f"```{product_price}円 × {quantity}個 - {discount}円 × {quantity}個 = {final_price}円```",
                    inline=False
                )
            else:
                embed.add_field(name="金額", value=f"```{final_price}円```", inline=False)
            
            embed.set_footer(text="Developer @m_shoppp")
            
            view = VendingMachineCog.PurchaseConfirmView(
                self.vending_machine_id,
                self.product,
                quantity,
                final_price,
                self.bot,
                self.payment_method
            )
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    class PurchaseConfirmView(ui.View):
        def __init__(self, vending_machine_id: str, product: dict, quantity: int, final_price: int, bot: commands.Bot, payment_method: str):
            super().__init__(timeout=300)
            self.vending_machine_id = vending_machine_id
            self.product = product
            self.quantity = quantity
            self.final_price = final_price
            self.bot = bot
            self.payment_method = payment_method

        @ui.button(label="購入確定", style=discord.ButtonStyle.green)
        async def confirm_purchase(self, interaction: discord.Interaction, button: ui.Button):
            if self.final_price == 0:
                await self.process_purchase(interaction, None)
            else:
                if self.payment_method.startswith("paypay"):
                    modal = VendingMachineCog.PayPayModal(
                        self.vending_machine_id,
                        self.product,
                        self.quantity,
                        self.final_price,
                        self.bot,
                        self.payment_method
                    )
                else:
                    modal = VendingMachineCog.KyashModal(
                        self.vending_machine_id,
                        self.product,
                        self.quantity,
                        self.final_price,
                        self.bot
                    )
                await interaction.response.send_modal(modal)

        async def process_purchase(self, interaction: discord.Interaction, link: Optional[str]):
            await interaction.response.defer(ephemeral=True)
            
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id)
                
                if not vm or not isinstance(vm, dict):
                    embed = discord.Embed(
                        title="エラー",
                        description="この自販機は削除されているか、データが不正です。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @m_shoppp")
                    return await interaction.followup.send(embed=embed, ephemeral=True)
                
                if self.final_price > 0:
                    if self.payment_method.startswith("paypay"):
                        payment_info = await paypayu.check_link(link)
                        if not payment_info:
                            return await interaction.followup.send("有効なPayPayリンクを入力してください。", ephemeral=True)

                        total_payment_amount = payment_info.get("payload", {}).get("message", {}).get("data", {}).get("amount")
                        if total_payment_amount < self.final_price:
                            return await interaction.followup.send(
                                f"金額が不足しています。\n必要な金額: {self.final_price}円\nあなたの支払額: {total_payment_amount}円",
                                ephemeral=True
                            )

                        # PayPayマネー / マネーライトの残高タイプ検証
                        # getP2PLinkInfo の payload.pendingP2PInfo.sendMoneyMethodType に残高タイプが入る
                        # 値: "MONEY"(マネー) / "MONEY_LITE"(マネーライト)
                        pending_info = payment_info.get("payload", {}).get("pendingP2PInfo", {})
                        send_money_type = str(pending_info.get("sendMoneyMethodType") or "").upper()
                        if send_money_type:
                            if self.payment_method == "paypay_money" and send_money_type != "MONEY":
                                return await interaction.followup.send(
                                    f"決済方法が一致しません。\n選択: **PayPayマネー** / リンクの残高タイプ: `{send_money_type}`\nPayPayマネーのリンクを送ってください。",
                                    ephemeral=True
                                )
                            if self.payment_method == "paypay_money_light" and send_money_type != "MONEY_LITE":
                                return await interaction.followup.send(
                                    f"決済方法が一致しません。\n選択: **PayPayマネーライト** / リンクの残高タイプ: `{send_money_type}`\nPayPayマネーライトのリンクを送ってください。",
                                    ephemeral=True
                                )

                        paypay_data = load_paypay_data()
                        owner_credentials = paypay_data.get(vm.get("paypay_id", ""))

                        if not owner_credentials:
                            return await interaction.followup.send("販売者のPayPayアカウントが設定されていません。\n販売者にお問い合わせください。", ephemeral=True)

                        result = await paypayu.link_rev(
                            link,
                            owner_credentials["phone"],
                            owner_credentials["password"],
                            owner_credentials["uuid"]
                        )
                        
                        if result == False:
                            try:
                                login_result = await paypayu.login(
                                    owner_credentials["phone"],
                                    owner_credentials["password"],
                                    owner_credentials["uuid"]
                                )
                                if login_result:
                                    result = await paypayu.link_rev(
                                        link,
                                        owner_credentials["phone"],
                                        owner_credentials["password"],
                                        owner_credentials["uuid"]
                                    )
                            except Exception as e:
                                print(f"自動再ログインエラー: {e}")
                        
                        if result != True:
                            return await interaction.followup.send("PayPay決済の処理に失敗しました。リンクが正しいか確認してください。", ephemeral=True)
                    
                    else:
                        kyash_data = load_kyash_data()
                        owner_kyash_info = kyash_data.get(vm.get("kyash_id", ""))
                        if not owner_kyash_info:
                            return await interaction.followup.send("販売者のKyashアカウントが設定されていません。", ephemeral=True)
                        
                        try:
                            kyash = Kyash(
                                client_uuid=owner_kyash_info.get("client_uuid"),
                                installation_uuid=owner_kyash_info.get("installation_uuid"),
                                access_token=owner_kyash_info.get("access_token")
                            )
                            
                            link_info = kyash.link_check(link)
                            if link_info.amount < self.final_price:
                                return await interaction.followup.send(
                                    f"金額が不足しています。\n必要な金額: {self.final_price}円\nリンク金額: {link_info.amount}円",
                                    ephemeral=True
                                )
                            
                            kyash.link_receive(link_info.uuid)
                        
                        except KyashError as e:
                            return await interaction.followup.send(f"Kyash決済エラー: {str(e)}", ephemeral=True)
                        except Exception as e:
                            return await interaction.followup.send(f"決済処理エラー: {str(e)}", ephemeral=True)

                if self.product.get("infinite_stock"):
                    purchased_content = f"```\n{self.product.get('infinite_content', '')}\n```"
                    purchased_content_text = self.product.get('infinite_content', '')
                else:
                    with open(self.product["stock_file"], "r+", encoding="utf-8") as file:
                        lines = [line for line in file.readlines() if line.strip()]
                        if len(lines) < self.quantity:
                            return await interaction.followup.send(
                                f"在庫が不足しています。\n必要数: {self.quantity}個\n現在の在庫: {len(lines)}個",
                                ephemeral=True
                            )
                        
                        purchased_items = lines[:self.quantity]
                        remaining_items = lines[self.quantity:]
                        file.seek(0)
                        file.truncate()
                        file.write("\n".join(remaining_items))
                    
                    purchased_content = f"```\n{''.join(purchased_items).strip()}\n```"
                    purchased_content_text = ''.join(purchased_items).strip()
                
                price_display = "0円" if self.final_price == 0 else f"{self.final_price}円"
                
                embed = discord.Embed(
                    title="購入完了",
                    description=f"**商品:** `{self.product['name']}`\n**数量:** `{self.quantity}`個\n**合計金額:** `{price_display}`",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="購入した商品", value=purchased_content, inline=False)
                embed.set_footer(text="Developer @m_shoppp")
                await interaction.followup.send(embed=embed, ephemeral=True)
                
                vending_data = load_json(VENDING_DATA_FILE)
                if self.vending_machine_id in vending_data and isinstance(vending_data[self.vending_machine_id], dict):
                    vm_ref = vending_data[self.vending_machine_id]
                    for i, p in enumerate(vm_ref.get("products", [])):
                        if p.get("product_id") == self.product.get("product_id"):
                            current_sales = p.get("sales_count", 0)
                            vm_ref["products"][i]["sales_count"] = current_sales + self.quantity
                            break
                    save_json(VENDING_DATA_FILE, vending_data)
                
                try:
                    role_data = load_role_assignment_data()
                    role_info = role_data.get(self.vending_machine_id)
                    if role_info and role_info.get("guild_id") == interaction.guild.id:
                        role = interaction.guild.get_role(int(role_info.get("role_id")))
                        if role and role not in interaction.user.roles:
                            await interaction.user.add_roles(role)
                except:
                    pass


                try:
                    import pytz
                    jst = pytz.timezone('Asia/Tokyo')
                    formatted_time = datetime.datetime.now(jst).strftime("%Y/%m/%d %H:%M:%S(JST)")
                    
                    dm_embed = discord.Embed(title="購入が完了しました", color=discord.Color.green(), timestamp=discord.utils.utcnow())
                    dm_embed.add_field(name="購入日", value=f"```{formatted_time}```", inline=True)
                    dm_embed.add_field(name="購入サーバー", value=f"```{interaction.guild.name}({interaction.guild.id})```", inline=True)
                    dm_embed.add_field(name="商品名", value=f"```{self.product['name']}```", inline=True)
                    dm_embed.add_field(name="購入数", value=f"```{self.quantity}個```", inline=True)
                    dm_embed.add_field(name="支払金額", value=f"```{price_display}```", inline=True)
                    dm_embed.add_field(name="決済方法", value=f"```{payment_method_label(self.payment_method)}```", inline=True)
                    dm_embed.set_footer(text="Developer @m_shoppp")
                    await interaction.user.send(purchased_content_text, embed=dm_embed)
                except discord.Forbidden:
                    try:
                        fallback_embed = discord.Embed(
                            title="⚠️ DMが送れませんでした",
                            description="DMの受信が許可されていないため、こちらに商品を送信します。内容を必ず保存してください。",
                            color=discord.Color.orange()
                        )
                        fallback_embed.set_footer(text="Developer @m_shoppp")
                        await interaction.followup.send(purchased_content_text, embed=fallback_embed, ephemeral=True)
                    except Exception:
                        pass
                except Exception as dm_err:
                    print(f"DM送信エラー: {dm_err}")
                    try:
                        fallback_embed = discord.Embed(
                            title="⚠️ DMが送れませんでした",
                            description="DM送信中にエラーが発生しました。こちらに商品を送信します。内容を必ず保存してください。",
                            color=discord.Color.orange()
                        )
                        fallback_embed.set_footer(text="Developer @m_shoppp")
                        await interaction.followup.send(purchased_content_text, embed=fallback_embed, ephemeral=True)
                    except Exception:
                        pass
                
                colors = [discord.Color.red(), discord.Color.blue(), discord.Color.green(), discord.Color.yellow(), discord.Color.purple(), discord.Color.orange(), discord.Color.pink(), discord.Color.teal(), discord.Color.magenta(), discord.Color.gold()]
                
                def create_log_embed():
                    emb = discord.Embed(color=random.choice(colors))
                    emb.add_field(name="商品名", value=f"```{self.product['name']}```", inline=True)
                    emb.add_field(name="購入数", value=f"```{self.quantity}個```", inline=True)
                    emb.add_field(name="購入サーバー", value=f"```{interaction.guild.name}```", inline=True)
                    emb.add_field(name="購入者", value=f"{interaction.user.mention}({interaction.user.id})", inline=True)
                    emb.add_field(name="決済方法", value=f"```{payment_method_label(self.payment_method)}```", inline=True)
                    emb.set_footer(text="Developer @m_shoppp")
                    return emb

                log_embed_obj = None

                if vm.get("log_channel_id"):
                    try:
                        global_log_channel = self.bot.get_channel(int(vm["log_channel_id"]))
                        if global_log_channel:
                            log_embed_obj = create_log_embed()
                            await global_log_channel.send(embed=log_embed_obj)
                    except:
                        pass

                local_channel_id = vm.get("server_logs", {}).get(str(interaction.guild.id))
                if local_channel_id:
                    try:
                        local_log_channel = self.bot.get_channel(int(local_channel_id))
                        if local_log_channel:
                            if not log_embed_obj: log_embed_obj = create_log_embed()
                            await local_log_channel.send(embed=log_embed_obj)
                    except:
                        pass
                
                if vm.get("private_log_channel_id"):
                    try:
                        private_log_channel = self.bot.get_channel(int(vm["private_log_channel_id"]))
                        if private_log_channel:
                            private_log_embed = discord.Embed(color=discord.Color.orange())
                            private_log_embed.add_field(name="商品名", value=f"```{self.product['name']}```", inline=True)
                            private_log_embed.add_field(name="購入数", value=f"```{self.quantity}個```", inline=True)
                            private_log_embed.add_field(name="購入サーバー", value=f"```{interaction.guild.name}```", inline=True)
                            private_log_embed.add_field(name="購入者", value=f"{interaction.user.mention}")
                            private_log_embed.add_field(name="支払金額", value=f"```{price_display}```", inline=True)
                            private_log_embed.add_field(name="決済方法", value=f"```{payment_method_label(self.payment_method)}```", inline=True)
                            private_log_embed.add_field(name="自販機", value=f"```{vm['name']}```", inline=True)
                            private_log_embed.set_footer(text="Developer @m_shoppp")
                            
                            discord_file = discord.File(
                                io.BytesIO(purchased_content_text.encode('utf-8')),
                                filename=f"purchase_{interaction.user.id}_{int(discord.utils.utcnow().timestamp())}.txt"
                            )
                            await private_log_channel.send(embed=private_log_embed, file=discord_file)
                    except:
                        pass
                
            except Exception as e:
                await handle_error(interaction, e)

    class PayPayModal(ui.Modal, title="PayPay決済"):
        def __init__(self, vending_machine_id: str, product: dict, quantity: int, final_price: int, bot: commands.Bot, payment_method: str):
            super().__init__()
            self.vending_machine_id = vending_machine_id
            self.product = product
            self.quantity = quantity
            self.final_price = final_price
            self.bot = bot
            self.payment_method = payment_method
            
            self.paypay_input = ui.TextInput(
                label="PayPayリンク", 
                placeholder="https://pay.paypay.ne.jp/...", 
                required=True
            )
            self.add_item(self.paypay_input)

        async def on_submit(self, interaction: discord.Interaction):
            confirm_view = VendingMachineCog.PurchaseConfirmView(
                self.vending_machine_id, 
                self.product, 
                self.quantity, 
                self.final_price, 
                self.bot,
                self.payment_method
            )
            await confirm_view.process_purchase(interaction, self.paypay_input.value)

    class KyashModal(ui.Modal, title="Kyash決済"):
        def __init__(self, vending_machine_id: str, product: dict, quantity: int, final_price: int, bot: commands.Bot):
            super().__init__()
            self.vending_machine_id = vending_machine_id
            self.product = product
            self.quantity = quantity
            self.final_price = final_price
            self.bot = bot
            
            self.kyash_input = ui.TextInput(
                label="Kyashリンク",
                placeholder="https://kyash.me/payments/...",
                required=True
            )
            self.add_item(self.kyash_input)

        async def on_submit(self, interaction: discord.Interaction):
            confirm_view = VendingMachineCog.PurchaseConfirmView(
                self.vending_machine_id,
                self.product,
                self.quantity,
                self.final_price,
                self.bot,
                "kyash"
            )
            await confirm_view.process_purchase(interaction, self.kyash_input.value)

    class ProductSelect(ui.Select):
        def __init__(self, vending_machine_id: str, bot: commands.Bot, payment_method: str):
            self.vending_machine_id = vending_machine_id
            self.bot = bot
            self.payment_method = payment_method
            
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id, {})
            products = vm.get("products", [])
            
            options = []
            if products:
                for product in products:
                    emoji = product.get("emoji")
                    label = f"{product['name']}"
                    price = get_product_price(product, payment_method)
                    
                    sales_count = product.get("sales_count", 0)
                    if product.get("infinite_stock"):
                        description = f"価格: {price}円│在庫数: ∞個│販売数: {sales_count}個"
                    else:
                        try:
                            with open(product.get("stock_file", ""), "r", encoding="utf-8") as f:
                                lines = [line for line in f.readlines() if line.strip()]
                                stock_count = len(lines)
                        except:
                            stock_count = 0
                        
                        description = f"価格: {price}円│在庫数: {stock_count}個│販売数: {sales_count}個"
                    
                    options.append(discord.SelectOption(
                        label=label,
                        value=product["product_id"],
                        description=description,
                        emoji=emoji
                    ))
            
            if not options:
                options.append(discord.SelectOption(label="商品なし", value="none", description="現在販売中の商品はありません"))
            
            super().__init__(
                placeholder="商品を選択する",
                options=options,
                custom_id=f"product_select_{vending_machine_id}_{payment_method}"
            )

        async def callback(self, interaction: discord.Interaction):
            if self.values[0] == "none":
                return await interaction.response.send_message("現在販売中の商品はありません。", ephemeral=True)
            
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id, {})
                if not vm:
                    embed = discord.Embed(
                        title="エラー",
                        description="この自販機は削除されているか、存在しません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @m_shoppp")
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
                
                products = vm.get("products", [])
                product = next((p for p in products if p["product_id"] == self.values[0]), None)
                if not product: 
                    return await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
                
                if product.get("infinite_stock"):
                    modal = VendingMachineCog.CouponModal(
                        self.vending_machine_id, 
                        product, 
                        self.bot,
                        self.payment_method
                    )
                    await interaction.response.send_modal(modal)
                else:
                    try:
                        with open(product.get("stock_file", ""), "r", encoding="utf-8") as f:
                            lines = [line for line in f.readlines() if line.strip()]
                            if len(lines) == 0:
                                embed = discord.Embed(
                                    title="在庫不足",
                                    description=f"現在 {product['name']}の在庫が不足しています。",
                                    color=discord.Color.orange()
                                )
                                embed.set_footer(text="Developer @m_shoppp")
                                return await interaction.response.send_message(embed=embed, ephemeral=True)
                    except:
                        embed = discord.Embed(
                            title="在庫不足",
                            description=f"現在 {product['name']}の在庫が不足しています。",
                            color=discord.Color.orange()
                        )
                        embed.set_footer(text="Developer @m_shoppp")
                        return await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                    modal = VendingMachineCog.CouponModal(
                        self.vending_machine_id, 
                        product, 
                        self.bot,
                        self.payment_method
                    )
                    await interaction.response.send_modal(modal)
                
            except Exception as e:
                await handle_error(interaction, e)

    class PurchaseButton(ui.Button):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            super().__init__(
                label="購入する",
                style=discord.ButtonStyle.green,
                emoji="🛒",
                custom_id=f"purchase_{vending_machine_id}"
            )
            self.vending_machine_id = vending_machine_id
            self.bot = bot

        async def callback(self, interaction: discord.Interaction):
            try:
                view = VendingMachineCog.PaymentMethodView(self.vending_machine_id, self.bot)
                await interaction.response.send_message(
                    "決済方法を選択してください。",
                    view=view,
                    ephemeral=True
                )
            except Exception as e:
                await handle_error(interaction, e)

    class ProductSelectView(ui.View):
        def __init__(self, vending_machine_id: str, bot: commands.Bot, payment_method: str):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.ProductSelect(vending_machine_id, bot, payment_method))

    class StockCheckButton(ui.Button):
        def __init__(self, vending_machine_id: str):
            super().__init__(
                label="在庫・販売数確認",
                style=discord.ButtonStyle.primary,
                emoji="📦",
                custom_id=f"check_stock_{vending_machine_id}"
            )
            self.vending_machine_id = vending_machine_id

        async def callback(self, interaction: discord.Interaction):
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vm = vending_data.get(self.vending_machine_id, {})
                if not vm:
                    embed = discord.Embed(
                        title="エラー",
                        description="この自販機は削除されているか、存在しません。",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text="Developer @m_shoppp")
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
                
                products = vm.get("products", [])
                await interaction.response.defer(ephemeral=True)
                await check_stock(interaction, products)
            except Exception as e:
                await handle_error(interaction, e)

    class VendingMachineView(ui.View):
        def __init__(self, vending_machine_id: str, bot: commands.Bot):
            super().__init__(timeout=None)
            self.vending_machine_id = vending_machine_id
            self.add_item(VendingMachineCog.PurchaseButton(vending_machine_id, bot))
            self.add_item(VendingMachineCog.StockCheckButton(vending_machine_id))

    class ProductSelectViewForStock(ui.View):
        def __init__(self, products: list, attachment: Optional[discord.Attachment] = None, stock_type: str = "finite"):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.ProductSelectForStock(products, attachment, stock_type))
            
    class ProductSelectForStock(ui.Select):
        def __init__(self, products: list, attachment: Optional[discord.Attachment] = None, stock_type: str = "finite"):
            self.products = products
            self.attachment = attachment
            self.stock_type = stock_type
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="在庫を追加する商品を選択...", 
                options=options,
                custom_id="stock_add_select"
            )

        async def callback(self, interaction: discord.Interaction):
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
                    return

                if self.stock_type == "infinite":
                    if self.attachment:
                        await interaction.response.defer(ephemeral=True)
                        try:
                            new_stock_content = await self.attachment.read()
                            infinite_content = new_stock_content.decode('utf-8').strip()
                            
                            vending_data = load_json(VENDING_DATA_FILE)
                            for vm_id, vm_data in vending_data.items():
                                for i, p in enumerate(vm_data.get("products", [])):
                                    if p["product_id"] == product["product_id"]:
                                        vm_data["products"][i]["infinite_stock"] = True
                                        vm_data["products"][i]["infinite_content"] = infinite_content
                                        break
                            save_json(VENDING_DATA_FILE, vending_data)
                            
                            await interaction.followup.send(f"商品「{product['name']}」を無限在庫に設定しました。", ephemeral=True)
                        except Exception as e:
                            await handle_error(interaction, e)
                    else:
                        modal = VendingMachineCog.InfiniteStockModal(product)
                        await interaction.response.send_modal(modal)
                else:
                    if self.attachment:
                        await interaction.response.defer(ephemeral=True)
                        try:
                            new_stock_content = await self.attachment.read()
                            new_stock_lines = [line for line in new_stock_content.decode('utf-8').splitlines() if line.strip()]
                            with open(product["stock_file"], "a", encoding="utf-8") as f:
                                if os.path.getsize(product["stock_file"]) > 0: 
                                    f.write("\n")
                                f.write("\n".join(new_stock_lines))
                            
                            await interaction.followup.send(f"商品「{product['name']}」に`{len(new_stock_lines)}`個の在庫を追加しました。", ephemeral=True)
                            
                            await self.send_stock_notification(interaction, product, len(new_stock_lines))
                            
                        except Exception as e:
                            await handle_error(interaction, e)
                    else:
                        modal = VendingMachineCog.StockAddModal(product)
                        await interaction.response.send_modal(modal)
            except Exception as e:
                await handle_error(interaction, e)
        
        async def send_stock_notification(self, interaction: discord.Interaction, product: dict, added_count: int):
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vending_machine_id = None
                for vm_id, vm_data in vending_data.items():
                    if not isinstance(vm_data, dict):
                        continue
                    for p in vm_data.get("products", []):
                        if p["product_id"] == product["product_id"]:
                            vending_machine_id = vm_id
                            break
                    if vending_machine_id:
                        break
                
                notification_data = load_stock_notification_data()
                notification_info = notification_data.get(vending_machine_id)
                
                if notification_info and notification_info.get("guild_id") == interaction.guild.id:
                    channel = interaction.guild.get_channel(notification_info.get("channel_id"))
                    role = interaction.guild.get_role(notification_info.get("role_id"))
                    
                    if channel and role:
                        embed = discord.Embed(
                            title="在庫追加通知",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="追加商品", value=f"```{product['name']}```", inline=True)
                        embed.add_field(name="追加数", value=f"```{added_count}個```", inline=True)
                        embed.set_footer(text="Developer @m_shoppp")
                        
                        await channel.send(f"{role.mention}", embed=embed)
                        
            except Exception as e:
                print(f"在庫追加通知送信エラー: {e}")

    class StockAddModal(ui.Modal, title="在庫追加"):
        def __init__(self, product: dict):
            super().__init__(timeout=None)
            self.product = product

        stock_input = ui.TextInput(
            label="在庫内容",
            style=discord.TextStyle.long,
            placeholder="追加する在庫を1行ずつ入力してください",
            required=True
        )

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                new_stock_lines = [line for line in self.stock_input.value.splitlines() if line.strip()]
                
                with open(self.product["stock_file"], "a", encoding="utf-8") as f:
                    if os.path.getsize(self.product["stock_file"]) > 0: 
                        f.write("\n")
                    f.write("\n".join(new_stock_lines))
                
                await interaction.followup.send(f"商品「{self.product['name']}」に`{len(new_stock_lines)}`個の在庫を追加しました。", ephemeral=True)
                
                await self.send_stock_notification(interaction, self.product, len(new_stock_lines))
                
            except Exception as e:
                await handle_error(interaction, e)
        
        async def send_stock_notification(self, interaction: discord.Interaction, product: dict, added_count: int):
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                vending_machine_id = None
                for vm_id, vm_data in vending_data.items():
                    if not isinstance(vm_data, dict):
                        continue
                    
                    for p in vm_data.get("products", []):
                        if p["product_id"] == product["product_id"]:
                            vending_machine_id = vm_id
                            break
                    if vending_machine_id:
                        break
                
                if not vending_machine_id:
                    return
                
                notification_data = load_stock_notification_data()
                notification_info = notification_data.get(vending_machine_id)
                
                if notification_info and notification_info.get("guild_id") == interaction.guild.id:
                    channel = interaction.guild.get_channel(notification_info.get("channel_id"))
                    role = interaction.guild.get_role(notification_info.get("role_id"))
                    
                    if channel and role:
                        embed = discord.Embed(
                            title="在庫追加通知",
                            color=discord.Color.blue(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="追加商品", value=f"```{product['name']}```", inline=True)
                        embed.add_field(name="追加数", value=f"```{added_count}個```", inline=True)
                        embed.set_footer(text="Developer @m_shoppp")
                        
                        await channel.send(f"{role.mention}", embed=embed)
                        
            except Exception as e:
                print(f"在庫追加通知送信エラー: {e}")

    class InfiniteStockModal(ui.Modal, title="無限在庫設定"):
        def __init__(self, product: dict):
            super().__init__(timeout=None)
            self.product = product

        stock_input = ui.TextInput(
            label="無限在庫内容",
            style=discord.TextStyle.long,
            placeholder="購入時に送信される内容を入力してください",
            required=True
        )

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                infinite_content = self.stock_input.value.strip()
                
                vending_data = load_json(VENDING_DATA_FILE)
                for vm_id, vm_data in vending_data.items():
                    if not isinstance(vm_data, dict):
                        continue
                        
                    for i, p in enumerate(vm_data.get("products", [])):
                        if p["product_id"] == self.product["product_id"]:
                            vm_data["products"][i]["infinite_stock"] = True
                            vm_data["products"][i]["infinite_content"] = infinite_content
                            break
                save_json(VENDING_DATA_FILE, vending_data)
                
                await interaction.followup.send(f"商品「{self.product['name']}」を無限在庫に設定しました。", ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

    class WithdrawStockView(ui.View):
        def __init__(self, products: list, quantity: int):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.ProductSelectForWithdraw(products, quantity))

    class ProductSelectForWithdraw(ui.Select):
        def __init__(self, products: list, quantity: int):
            self.products = products
            self.quantity = quantity
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="在庫を引き出す商品を選択...", 
                options=options,
                custom_id="withdraw_select"
            )

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.followup.send("商品が見つかりません。", ephemeral=True)
                    return

                if product.get("infinite_stock"):
                    vending_data = load_json(VENDING_DATA_FILE)
                    withdrawn_content = ""
                    for vm_id, vm_data in vending_data.items():
                        if not isinstance(vm_data, dict): 
                            continue
                        for i, p in enumerate(vm_data.get("products", [])):
                            if p["product_id"] == product["product_id"]:
                                withdrawn_content = f"`{p.get('infinite_content', '')}\n`"
                                vm_data["products"][i]["infinite_stock"] = False
                                vm_data["products"][i]["infinite_content"] = None
                                break
                    save_json(VENDING_DATA_FILE, vending_data)
                    
                    embed = discord.Embed(
                        title="無限在庫解除完了",
                        description=f"**商品:** `{product['name']}`\n**解除された無限在庫内容:**",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="引き出した無限在庫", value=withdrawn_content, inline=False)
                    embed.set_footer(text="Developer @m_shoppp")
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    try:
                        with open(product["stock_file"], "r+", encoding="utf-8") as file:
                            lines = [line for line in file.readlines() if line.strip()]
                            
                            if len(lines) < self.quantity:
                                await interaction.followup.send(
                                    f"在庫が不足しています。\n引出希望数: {self.quantity}個\n現在の在庫: {len(lines)}個",
                                    ephemeral=True
                                )
                                return
                            
                            withdrawn_items = lines[:self.quantity]
                            remaining_items = lines[self.quantity:]
                            
                            file.seek(0)
                            file.truncate()
                            file.write("\n".join(remaining_items))
                        
                        withdrawn_content = f"`{''.join(withdrawn_items).strip()}\n`"
                        
                        embed = discord.Embed(
                            title="在庫引出完了",
                            description=f"**商品:** `{product['name']}`\n**引出数量:** `{self.quantity}`個",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="引き出した在庫", value=withdrawn_content, inline=False)
                        embed.set_footer(text="Developer @m_shoppp")
                        
                        await interaction.followup.send(embed=embed, ephemeral=True)

                    except FileNotFoundError:
                        await handle_error(interaction, FileNotFoundError("在庫ファイルが見つかりません。"))
                    except Exception as e:
                        await handle_error(interaction, e)
            except Exception as e:
                await handle_error(interaction, e)

    class ContentView(ui.View):
        def __init__(self, products: list):
            super().__init__(timeout=None)
            self.add_item(VendingMachineCog.ProductSelectForContent(products))

    class ProductSelectForContent(ui.Select):
        def __init__(self, products: list):
            self.products = products
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="在庫内容を確認する商品を選択...", 
                options=options,
                custom_id="content_select"
            )

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.followup.send("商品が見つかりません。", ephemeral=True)
                    return

                if product.get("infinite_stock"):
                    infinite_content = product.get("infinite_content", "")
                    stock_content = f"`{infinite_content}\n`"
                    
                    embed = discord.Embed(
                        title="在庫内容",
                        description=f"**商品:** `{product['name']}`\n**在庫数:** `∞`個",
                        color=discord.Color.blue(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="無限在庫内容", value=stock_content, inline=False)
                    embed.set_footer(text="Developer @m_shoppp")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    try:
                        with open(product["stock_file"], "r", encoding="utf-8") as file:
                            content = file.read().strip()
                            
                            if not content:
                                embed = discord.Embed(
                                    title="在庫内容",
                                    description=f"**商品:** `{product['name']}`\n**在庫数:** `0`個",
                                    color=discord.Color.blue(),
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.add_field(name="在庫内容", value="```\n在庫がありません\n```", inline=False)
                            else:
                                lines = [line for line in content.splitlines() if line.strip()]
                                stock_content = f"`{content}`\n"
                                
                                embed = discord.Embed(
                                    title="在庫内容",
                                    description=f"**商品:** `{product['name']}`\n**在庫数:** `{len(lines)}`個",
                                    color=discord.Color.blue(),
                                    timestamp=discord.utils.utcnow()
                                )
                                embed.add_field(name="在庫内容", value=stock_content, inline=False)
                            
                            embed.set_footer(text="Developer @m_shoppp")
                            await interaction.followup.send(embed=embed, ephemeral=True)

                    except FileNotFoundError:
                        await handle_error(interaction, FileNotFoundError("在庫ファイルが見つかりません。"))
                    except Exception as e:
                        await handle_error(interaction, e)
            except Exception as e:
                await handle_error(interaction, e)

    class ProductSelectForDelete(ui.Select):
        def __init__(self, products: list):
            self.products = products
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="削除する商品を選択...", 
                options=options,
                custom_id="delete_select"
            )

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.followup.send("商品が見つかりません。", ephemeral=True)
                    return

                view = VendingMachineCog.DeleteConfirmView(product)
                embed = discord.Embed(
                    title="商品削除確認",
                    description=f"本当に商品「{product['name']}」を削除しますか？\n\n**この操作は取り消せません。**",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Developer @m_shoppp")
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

    class ProductDeleteView(ui.View):
        def __init__(self, products: list, vending_machine_id: str):
            super().__init__(timeout=None)
            self.vending_machine_id = vending_machine_id
            self.add_item(VendingMachineCog.ProductSelectForDelete(products))

    class DeleteConfirmView(ui.View):
        def __init__(self, product: dict):
            super().__init__(timeout=None)
            self.product = product

        @ui.button(label="削除する", style=discord.ButtonStyle.danger)
        async def confirm_delete(self, interaction: discord.Interaction, button: ui.Button):
            await interaction.response.defer(ephemeral=True)
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                for vm_id, vm_data in vending_data.items():
                    if not isinstance(vm_data, dict): 
                        continue
                    vm_data["products"] = [p for p in vm_data.get("products", []) if p["product_id"] != self.product["product_id"]]
                
                save_json(VENDING_DATA_FILE, vending_data)
                
                try:
                    if os.path.exists(self.product["stock_file"]):
                        os.remove(self.product["stock_file"])
                except:
                    pass
                
                embed = discord.Embed(
                    title="削除完了",
                    description=f"商品「{self.product['name']}」を削除しました。",
                    color=discord.Color.green()
                )
                embed.set_footer(text="Developer @m_shoppp")
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

        @ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
        async def cancel_delete(self, interaction: discord.Interaction, button: ui.Button):
            embed = discord.Embed(title="キャンセル", description="商品削除をキャンセルしました。", color=discord.Color.blue())
            embed.set_footer(text="Developer @m_shoppp")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    class EditProductView(ui.View):
        def __init__(self, products: list, vending_machine_id: str):
            super().__init__(timeout=None)
            self.vending_machine_id = vending_machine_id
            self.add_item(VendingMachineCog.ProductSelectForEdit(products, vending_machine_id))

    class ProductSelectForEdit(ui.Select):
        def __init__(self, products: list, vending_machine_id: str):
            self.products = products
            self.vending_machine_id = vending_machine_id
            options = [discord.SelectOption(label=p["name"], value=p["product_id"]) for p in products]
            super().__init__(
                placeholder="編集する商品を選択...", 
                options=options,
                custom_id="edit_select"
            )

        async def callback(self, interaction: discord.Interaction):
            try:
                product = next((p for p in self.products if p["product_id"] == self.values[0]), None)
                if not product:
                    await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
                    return
                modal = VendingMachineCog.EditProductModal(product, self.vending_machine_id)
                await interaction.response.send_modal(modal)
            except Exception as e:
                await handle_error(interaction, e)

    class EditProductModal(ui.Modal, title="商品情報編集"):
        name_input = ui.TextInput(label="商品名", placeholder="新しい商品名を入力...", required=False, max_length=100)
        description_input = ui.TextInput(label="商品説明", style=discord.TextStyle.long, placeholder="新しい商品説明を入力...", required=False, max_length=1000)
        paypay_prices_input = ui.TextInput(label="PayPay価格", placeholder="マネー,マネライト", required=False, max_length=40)
        price_kyash_input = ui.TextInput(label="Kyash価格", placeholder="新しいKyash価格を入力...", required=False, max_length=10)
        emoji_input = ui.TextInput(label="絵文字", placeholder="新しい絵文字を入力...", required=False, max_length=50)

        def __init__(self, product: dict, vending_machine_id: str):
            super().__init__(timeout=None)
            self.product = product
            self.vending_machine_id = vending_machine_id
            self.name_input.default = product.get("name", "")
            self.description_input.default = product.get("description", "")
            normalized = normalize_product_prices(product)
            self.paypay_prices_input.default = (
                f"{normalized.get('price_paypay_money', 0)},"
                f"{normalized.get('price_paypay_money_light', 0)}"
            )
            self.price_kyash_input.default = str(product.get("price_kyash", 0))
            self.emoji_input.default = product.get("emoji", "")

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            try:
                vending_data = load_json(VENDING_DATA_FILE)
                updated_fields = []
                for vm_id, vm_data in vending_data.items():
                    if not isinstance(vm_data, dict): 
                        continue
                    for p in vm_data.get("products", []):
                        if p["product_id"] == self.product["product_id"]:
                            if self.name_input.value.strip():
                                p["name"] = self.name_input.value.strip()
                                updated_fields.append("商品名")
                            if self.description_input.value is not None:
                                p["description"] = self.description_input.value.strip()
                                updated_fields.append("商品説明")
                            if self.paypay_prices_input.value.strip():
                                try:
                                    raw_values = [value.strip() for value in self.paypay_prices_input.value.split(",")]
                                    if len(raw_values) != 2:
                                        return await interaction.followup.send("PayPay価格は `マネー,マネライト` の2つで入力してください。", ephemeral=True)
                                    money_price, money_light_price = [int(value) for value in raw_values]
                                    if min(money_price, money_light_price) < 0:
                                        return await interaction.followup.send("PayPay価格は0以上で入力してください。", ephemeral=True)
                                    p["price_paypay"] = money_price
                                    p["price_paypay_money"] = money_price
                                    p["price_paypay_money_light"] = money_light_price
                                    updated_fields.append("PayPay価格")
                                except ValueError:
                                    return await interaction.followup.send("PayPay価格には整数を入力してください。", ephemeral=True)
                            if self.price_kyash_input.value.strip():
                                try:
                                    new_price = int(self.price_kyash_input.value.strip())
                                    if new_price >= 0:
                                        p["price_kyash"] = new_price
                                        updated_fields.append("Kyash価格")
                                    else:
                                        return await interaction.followup.send("Kyash価格は0以上で入力してください。", ephemeral=True)
                                except ValueError:
                                    return await interaction.followup.send("Kyash価格には整数を入力してください。", ephemeral=True)
                            if self.emoji_input.value.strip():
                                p["emoji"] = self.emoji_input.value.strip()
                                updated_fields.append("絵文字")
                            break
                
                if updated_fields:
                    save_json(VENDING_DATA_FILE, vending_data)
                    embed = discord.Embed(
                        title="商品情報更新完了",
                        description=f"商品「{self.product['name']}」を更新しました:\n• " + "\n• ".join(updated_fields),
                        color=discord.Color.green()
                    )
                    embed.set_footer(text="Developer @m_shoppp")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send("更新する項目が入力されていません。", ephemeral=True)
            except Exception as e:
                await handle_error(interaction, e)

    @app_commands.command(name="在庫追加通知設定", description="在庫追加時の通知設定を行います")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    @app_commands.describe(vending_machine_id="通知設定する自販機", channel="通知を送信するチャンネル", role="メンションするロール")
    async def stock_notification_setup(self, interaction: discord.Interaction, vending_machine_id: str, channel: discord.TextChannel, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.followup.send("指定された自販機が見つかりません。", ephemeral=True)
            
            notification_data = load_stock_notification_data()
            notification_data[vending_machine_id] = {
                "channel_id": channel.id,
                "role_id": role.id,
                "guild_id": interaction.guild.id
            }
            save_stock_notification_data(notification_data)
            
            embed = discord.Embed(title="在庫追加通知設定", description=f"自販機「{vm['name']}」の在庫追加通知を設定しました。", color=discord.Color.green())
            embed.add_field(name="通知チャンネル", value=channel.mention, inline=True)
            embed.add_field(name="メンションロール", value=role.mention, inline=True)
            embed.set_footer(text="Developer @m_shoppp")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="在庫追加設定解除", description="在庫追加通知設定を解除します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    async def stock_notification_remove(self, interaction: discord.Interaction, vending_machine_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.followup.send("指定された自販機が見つかりません。", ephemeral=True)
            
            notification_data = load_stock_notification_data()
            if vending_machine_id in notification_data:
                del notification_data[vending_machine_id]
                save_stock_notification_data(notification_data)
                await interaction.followup.send(f"自販機「{vm['name']}」の在庫追加通知設定を解除しました。", ephemeral=True)
            else:
                await interaction.followup.send("通知設定が見つかりません。", ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="自販機クーポン作成", description="指定した自販機用のクーポンコードを作成します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    async def vm_create_coupon(self, interaction: discord.Interaction, vending_machine_id: str, coupon_code: str, discount: int):
        try:
            if discount <= 0:
                return await interaction.response.send_message("割引金額は1円以上で指定してください。", ephemeral=True)
            
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("指定された自販機が見つかりません。", ephemeral=True)
            
            coupon_data = load_coupon_data()
            if coupon_code in coupon_data:
                return await interaction.response.send_message("そのコードは既に存在します。", ephemeral=True)
            
            coupon_data[coupon_code] = {
                "discount": discount,
                "owner_id": str(interaction.user.id),
                "vending_machine_id": vending_machine_id,
                "created_at": str(discord.utils.utcnow())
            }
            save_coupon_data(coupon_data)
            await interaction.response.send_message(f"クーポン「{coupon_code}」を作成しました。", ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(
        name="自販機クーポン削除",
        description="【管理者専用】クーポンを削除します"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def vm_delete_coupon(
        self,
        interaction: discord.Interaction,
        coupon_code: str
    ):
        try:
            coupon_data = load_coupon_data()

            if coupon_code not in coupon_data:
                await interaction.response.send_message(
                    f"❌ クーポン `{coupon_code}` は存在しません。",
                    ephemeral=True
                )
                return

            del coupon_data[coupon_code]
            save_coupon_data(coupon_data)

            await interaction.response.send_message(
                f"✅ クーポン `{coupon_code}` を削除しました。",
                ephemeral=True
            )
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="自販機クーポン一覧", description="作成したクーポン一覧を表示します")
    @is_allowed()
    async def vm_list_coupons(self, interaction: discord.Interaction):
        try:
            coupon_data = load_coupon_data()
            vending_data = load_json(VENDING_DATA_FILE)
            user_id = str(interaction.user.id)
            user_coupons = {k: v for k, v in coupon_data.items() if v.get("owner_id") == user_id}

            if not user_coupons:
                return await interaction.response.send_message("クーポンがありません。", ephemeral=True)

            embed = discord.Embed(title="クーポン一覧", color=discord.Color.blue())
            for code, info in user_coupons.items():
                vm_name = vending_data.get(info.get("vending_machine_id"), {}).get("name", "不明")
                embed.add_field(name=f"コード: {code}", value=f"割引: {info['discount']}円\n自販機: {vm_name}", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="自販機ロール設定", description="購入時に付与するロールを設定します")
    @is_allowed()
    @app_commands.autocomplete(vending_machine_id=vending_machine_autocomplete)
    async def vm_set_role(self, interaction: discord.Interaction, vending_machine_id: str, role: discord.Role):
        try:
            vending_data = load_json(VENDING_DATA_FILE)
            vm = vending_data.get(vending_machine_id)
            if not vm or vm.get("owner_id") != str(interaction.user.id):
                return await interaction.response.send_message("自販機が見つかりません。", ephemeral=True)

            role_data = load_role_assignment_data()
            role_data[vending_machine_id] = {"role_id": role.id, "guild_id": interaction.guild.id}
            save_role_assignment_data(role_data)
            await interaction.response.send_message(f"ロール {role.mention} を設定しました。", ephemeral=True)
        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot):
    await bot.add_cog(VendingMachineCog(bot))
