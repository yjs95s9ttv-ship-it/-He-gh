import os
import asyncio
from pathlib import Path
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import sqlite3
from collections import defaultdict

# ============================================================
# 1. 設定の読み込み
# ============================================================
load_dotenv('token.env')
TOKEN = os.getenv("TOKEN")

# ============================================================
# 2. パス設定 (AGAMES環境)
# ============================================================
PARENT_DIR = Path("/home/container")
COG_DIR = PARENT_DIR / "Cog"
DB_PATH = PARENT_DIR / "rental.db"

# ============================================================
# ★ 権限設定エリア ★
# ============================================================

ADMIN_USER_IDS: list[int] = [
    1465368277663350794,
]

# 製作者のサーバーID（/rentalコマンドをここだけに同期して非表示化）
OWNER_GUILD_ID: int = 1489162250601103362

# ============================================================
# 3. 貸し出しDB管理
# ============================================================

def init_rental_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS rentals (
            guild_id  INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            note      TEXT DEFAULT '',
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    con.commit()
    con.close()

def rental_is_allowed(guild_id: int, user_id: int) -> bool:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT 1 FROM rentals WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()
    con.close()
    return row is not None

def rental_is_allowed_for_guild(guild_id: int) -> bool:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT 1 FROM rentals WHERE guild_id=? AND user_id=0",
        (guild_id,)
    ).fetchone()
    con.close()
    return row is not None

def rental_add(guild_id: int, user_id: int, note: str = ""):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR REPLACE INTO rentals (guild_id, user_id, note) VALUES (?,?,?)",
        (guild_id, user_id, note)
    )
    con.commit()
    con.close()

def rental_remove(guild_id: int, user_id: int):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "DELETE FROM rentals WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )
    con.commit()
    con.close()

def rental_list() -> list[tuple[int, int, str]]:
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT guild_id, user_id, note FROM rentals ORDER BY guild_id").fetchall()
    con.close()
    return rows

def rental_remove_guild(guild_id: int):
    """サーバーに紐づく全ユーザー権限を削除"""
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM rentals WHERE guild_id=?", (guild_id,))
    con.commit()
    con.close()

# ============================================================
# 4. 製作者チェッカー
# ============================================================

def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in ADMIN_USER_IDS:
            return True
        await interaction.response.send_message(
            "❌ このコマンドは製作者のみ使用できます。",
            ephemeral=True,
        )
        return False
    return app_commands.check(predicate)

def check_permission(guild_id: int | None, user_id: int) -> bool:
    """スラッシュ・テキスト両方から呼べる共通チェック"""
    if user_id in ADMIN_USER_IDS:
        return True
    if guild_id is None:
        return True
    return rental_is_allowed_for_guild(guild_id) or rental_is_allowed(guild_id, user_id)

# ============================================================
# 5. サーバー管理UI（ボタンで退出・権限削除）
# ============================================================

class ServerManageView(discord.ui.View):
    """サーバー一覧の各サーバーに退出・権限削除ボタンを付けるView"""
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=60)
        self.target_guild = guild

    @discord.ui.button(label="🚪 退出", style=discord.ButtonStyle.danger)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in ADMIN_USER_IDS:
            await interaction.response.send_message("❌ 製作者のみ使用できます。", ephemeral=True)
            return
        name = self.target_guild.name
        gid = self.target_guild.id
        await self.target_guild.leave()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **{name}** (`{gid}`) から退出しました。",
            view=self,
        )

    @discord.ui.button(label="🗑️ 権限削除", style=discord.ButtonStyle.secondary)
    async def remove_rental_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in ADMIN_USER_IDS:
            await interaction.response.send_message("❌ 製作者のみ使用できます。", ephemeral=True)
            return
        rental_remove_guild(self.target_guild.id)
        await interaction.response.send_message(
            f"✅ **{self.target_guild.name}** の全権限を削除しました。",
            ephemeral=True,
        )

    @discord.ui.button(label="🚪＋🗑️ 退出＆権限削除", style=discord.ButtonStyle.danger)
    async def leave_and_remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in ADMIN_USER_IDS:
            await interaction.response.send_message("❌ 製作者のみ使用できます。", ephemeral=True)
            return
        name = self.target_guild.name
        gid = self.target_guild.id
        rental_remove_guild(gid)
        await self.target_guild.leave()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **{name}** (`{gid}`) から退出＆権限削除しました。",
            view=self,
        )

# ============================================================
# 6. Botクラス
# ============================================================

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)
        self.is_admin = is_admin
        init_rental_db()

    async def setup_hook(self):
        if OWNER_GUILD_ID:
            owner_guild = discord.Object(id=OWNER_GUILD_ID)
            self.tree.add_command(rental_group, guild=owner_guild)
        else:
            self.tree.add_command(rental_group)

        if COG_DIR.exists():
            for cog_file in COG_DIR.rglob("*.py"):
                if cog_file.name.startswith("__"):
                    continue
                try:
                    rel_path = cog_file.relative_to(PARENT_DIR).with_suffix("")
                    module_name = ".".join(rel_path.parts)
                    await self.load_extension(module_name)
                    print(f"✅ Loaded: {module_name}")
                except Exception as e:
                    print(f"❌ Error loading {cog_file.name}: {e}")

        print("🔄 同期中...")
        if OWNER_GUILD_ID:
            owner_guild = discord.Object(id=OWNER_GUILD_ID)
            await self.tree.sync(guild=owner_guild)
        await self.tree.sync()
        print("✅ 同期完了")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """スラッシュコマンド共通の権限チェック"""
        if check_permission(interaction.guild_id, interaction.user.id):
            return True
        # rentalコマンド自体は通す
        if interaction.command and interaction.command.qualified_name.startswith("rental"):
            return True
        await interaction.response.send_message(
            "❌ このbotの使用権限がありません。\n製作者にお問い合わせください。",
            ephemeral=True,
        )
        return False

    async def on_message(self, message: discord.Message):
        """テキストコマンド（acc/abb/add/aee）の権限チェック"""
        if message.author.bot:
            return
        content = message.content.strip().lower()
        # カジノ系テキストコマンドのプレフィックス
        if content.split()[0] if content.split() else "" in ("acc", "abb", "add", "aee"):
            guild_id = message.guild.id if message.guild else None
            if not check_permission(guild_id, message.author.id):
                await message.reply(
                    "❌ このbotの使用権限がありません。\n製作者にお問い合わせください。",
                    ephemeral=False,
                    delete_after=5,
                    mention_author=False,
                )
                return
        await self.process_commands(message)

    async def on_guild_join(self, guild: discord.Guild):
        """未許可サーバーに招待されたら自動退出"""
        if guild.id == OWNER_GUILD_ID:
            return

        # DBに許可エントリがあるサーバーは通す
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            "SELECT 1 FROM rentals WHERE guild_id=?", (guild.id,)
        ).fetchone()
        con.close()
        if row:
            return

        # adminがいるサーバーも通す（fetch_memberで確実に取得）
        for uid in ADMIN_USER_IDS:
            try:
                await guild.fetch_member(uid)
                return
            except discord.NotFound:
                pass

        print(f"[rental] 未許可サーバー '{guild.name}' ({guild.id}) から自動退出します。")
        try:
            if guild.system_channel:
                await guild.system_channel.send(
                    "このbotの使用には製作者による許可が必要です。\n"
                    "許可なく招待されたため自動退出します。"
                )
        except Exception:
            pass
        await guild.leave()


client = MyBot()

# ============================================================
# 7. 製作者専用コマンド（/rental）
# ============================================================

rental_group = app_commands.Group(name="rental", description="【製作者専用】bot管理")

@rental_group.command(name="add", description="【製作者専用】サーバーまたはユーザーに使用権限を付与する")
@app_commands.describe(guild_id="対象のサーバーID", user_id="対象のユーザーID（省略でサーバー全体）", note="メモ（任意）")
async def rental_add_cmd(interaction: discord.Interaction, guild_id: str, user_id: str | None = None, note: str = ""):
    if interaction.user.id not in ADMIN_USER_IDS:
        await interaction.response.send_message("❌ 製作者のみ使用できます。", ephemeral=True)
        return
    try:
        gid = int(guild_id)
        uid = 0 if user_id is None else int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ IDは数字で入力してください。", ephemeral=True)
        return
    rental_add(gid, uid, note)
    target_text = "サーバー全体" if uid == 0 else f"ユーザーID: `{uid}`"
    await interaction.response.send_message(
        f"✅ 権限を付与しました。\nサーバーID: `{gid}`\n対象: {target_text}\nメモ: {note or 'なし'}",
        ephemeral=True,
    )

@rental_group.command(name="remove", description="【製作者専用】サーバーまたはユーザーの使用権限を削除する")
@app_commands.describe(guild_id="対象のサーバーID", user_id="対象のユーザーID（省略でサーバー全体）")
async def rental_remove_cmd(interaction: discord.Interaction, guild_id: str, user_id: str | None = None):
    if interaction.user.id not in ADMIN_USER_IDS:
        await interaction.response.send_message("❌ 製作者のみ使用できます。", ephemeral=True)
        return
    try:
        gid = int(guild_id)
        uid = 0 if user_id is None else int(user_id)
    except ValueError:
        await interaction.response.send_message("❌ IDは数字で入力してください。", ephemeral=True)
        return
    rental_remove(gid, uid)
    target_text = "サーバー全体" if uid == 0 else f"ユーザーID: `{uid}`"
    await interaction.response.send_message(
        f"✅ 権限を削除しました。\nサーバーID: `{gid}`\n対象: {target_text}",
        ephemeral=True,
    )

@rental_group.command(name="list", description="【製作者専用】現在の貸し出しリストを表示する")
async def rental_list_cmd(interaction: discord.Interaction):
    if interaction.user.id not in ADMIN_USER_IDS:
        await interaction.response.send_message("❌ 製作者のみ使用できます。", ephemeral=True)
        return
    rows = rental_list()
    if not rows:
        await interaction.response.send_message("現在の貸し出しはありません。", ephemeral=True)
        return
    embed = discord.Embed(title="📋 貸し出しリスト", color=discord.Color.blurple())
    grouped: dict[int, list] = defaultdict(list)
    for gid, uid, note in rows:
        grouped[gid].append((uid, note))
    for gid, users in grouped.items():
        guild = client.get_guild(gid)
        guild_name = guild.name if guild else "不明なサーバー"
        lines = []
        for uid, note in users:
            if uid == 0:
                lines.append(f"• サーバー全体　{note or 'メモなし'}")
                continue
            user = client.get_user(uid)
            user_str = f"{user} (`{uid}`)" if user else f"`{uid}`"
            lines.append(f"• {user_str}　{note or 'メモなし'}")
        embed.add_field(name=f"🏠 {guild_name} (`{gid}`)", value="\n".join(lines), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@rental_group.command(name="server_list", description="【製作者専用】botが参加中のサーバー一覧をボタン付きで表示する")
async def rental_server_list_cmd(interaction: discord.Interaction):
    if interaction.user.id not in ADMIN_USER_IDS:
        await interaction.response.send_message("❌ 製作者のみ使用できます。", ephemeral=True)
        return
    guilds = client.guilds
    if not guilds:
        await interaction.response.send_message("現在どのサーバーにも参加していません。", ephemeral=True)
        return

    await interaction.response.send_message(
        f"🌐 **参加中サーバー一覧（{len(guilds)}件）**\n各サーバーのボタンで操作できます。",
        ephemeral=True,
    )
    for g in guilds:
        owner = client.get_user(g.owner_id) if g.owner_id else None
        owner_str = str(owner) if owner else f"ID:{g.owner_id}"
        view = ServerManageView(g)
        await interaction.followup.send(
            f"**{g.name}**　ID:`{g.id}`　メンバー:{g.member_count}人　オーナー:{owner_str}",
            view=view,
            ephemeral=True,
        )

# ============================================================
# 8. ステータス自動更新
# ============================================================

@tasks.loop(minutes=5)
async def update_status():
    await client.change_presence(activity=discord.Game(name="ぷにぷにフレンド募集中！"))

@client.event
async def on_ready():
    print(f"🤖 起動完了: {client.user}")
    if not update_status.is_running():
        update_status.start()

# ============================================================
# 9. 実行
# ============================================================

async def main():
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
