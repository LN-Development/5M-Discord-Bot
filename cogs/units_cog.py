# cogs/units_cog.py
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import json
import aiosqlite
import random
import string
from datetime import datetime, timedelta
import logging

# --- 1. Carregar Configurações ---
try:
    with open('config_units.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logging.critical("ERRO CRÍTICO: 'config_units.json' não foi encontrado.")
    exit()

GUILD_ID = config.get('GUILD_ID')
ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
DASHBOARD_CHANNEL_ID = config.get('DASHBOARD_CHANNEL_ID')
UNIT_LOG_CHANNEL_ID = config.get('UNIT_LOG_CHANNEL_ID')
UNIT_VOICE_CHANNEL_IDS = config.get('UNIT_VOICE_CHANNEL_IDS', [])
MESSAGES = config.get('MESSAGES', {})
DB_FILE = "unidades.sqlite"

# --- 2. Modais ---
class CreateUnitModal(Modal, title="Criar Nova Unidade"):
    unit_name = TextInput(label="Nome da Unidade", placeholder="Ex: Equipe Alpha", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.get_cog('UnitsCog')
        if await cog.get_user_unit_id(interaction.user.id):
            await interaction.followup.send(MESSAGES.get("ERROR_ALREADY_IN_UNIT"), ephemeral=True)
            return
        await cog.create_new_unit(interaction, self.unit_name.value)

class JoinUnitModal(Modal, title="Entrar em uma Unidade"):
    unit_id_input = TextInput(label="ID da Unidade", placeholder="Insira o ID de 6 caracteres", required=True, min_length=6, max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('UnitsCog')
        unit_id = str(self.unit_id_input).upper()
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT name FROM units WHERE unit_id = ?", (unit_id,)) as cursor:
                unit = await cursor.fetchone()
            if not unit:
                await interaction.response.send_message(MESSAGES.get("ERROR_UNIT_NOT_FOUND"), ephemeral=True)
                return
            if await cog.get_user_unit_id(interaction.user.id):
                await interaction.response.send_message(MESSAGES.get("ERROR_ALREADY_IN_UNIT"), ephemeral=True)
                return
            await db.execute("INSERT INTO unit_members (user_id, unit_id) VALUES (?, ?)", (interaction.user.id, unit_id))
            await db.commit()
        
        cog.logger.info(f"Usuário {interaction.user.display_name} entrou na unidade '{unit[0]}'.")
        await interaction.response.send_message(MESSAGES.get("SUCCESS_JOIN_UNIT").format(unit_name=unit[0]), ephemeral=True)
        await cog.update_dashboard_message()
        await cog.update_unit_log_message(unit_id) # CORREÇÃO: Atualiza o log da unidade

# --- 3. View Persistente ---
class UnitDashboardView(View):
    def __init__(self, bot_instance: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot_instance

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_voice_state = interaction.user.voice
        if not user_voice_state or not user_voice_state.channel or user_voice_state.channel.id not in UNIT_VOICE_CHANNEL_IDS:
            channel_names = [f"**{c.name}**" for cid in UNIT_VOICE_CHANNEL_IDS if (c := interaction.guild.get_channel(cid))]
            await interaction.response.send_message(MESSAGES.get('ERROR_NOT_IN_VOICE_CHANNEL').format(channel_names=", ".join(channel_names) or "N/A"), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Criar Unidade", style=discord.ButtonStyle.success, custom_id="unit_create_v3")
    async def create_unit(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(CreateUnitModal())

    @discord.ui.button(label="Entrar em Unidade", style=discord.ButtonStyle.primary, custom_id="unit_join_v3")
    async def join_unit(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(JoinUnitModal())

    @discord.ui.button(label="Sair da Unidade", style=discord.ButtonStyle.danger, custom_id="unit_leave_v3")
    async def leave_unit(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        cog_instance = self.bot.get_cog("UnitsCog")
        _, status_message = await cog_instance.execute_leave_unit(interaction.user, "Saída voluntária")
        await interaction.followup.send(status_message, ephemeral=True)

# --- 4. Classe do Cog de Unidades ---
class UnitsCog(commands.Cog, name="UnitsCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger('discord_bot')
        self.bot.add_view(UnitDashboardView(self.bot))
        self.check_expired_units.start()
        self.logger.info("Cog de Unidades carregado.")

    async def cog_load(self):
        await self.setup_database()

    def cog_unload(self):
        self.check_expired_units.cancel()

    async def setup_database(self):
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS units (unit_id TEXT PRIMARY KEY, name TEXT, creator_id INTEGER, created_at TEXT, log_message_id INTEGER)')
            cursor = await db.execute("PRAGMA table_info(units)")
            columns = {row[1] for row in await cursor.fetchall()}
            if 'log_message_id' not in columns:
                await db.execute("ALTER TABLE units ADD COLUMN log_message_id INTEGER")
            await db.execute('CREATE TABLE IF NOT EXISTS unit_members (user_id INTEGER PRIMARY KEY, unit_id TEXT, FOREIGN KEY (unit_id) REFERENCES units (unit_id) ON DELETE CASCADE)')
            await db.commit()
        self.logger.info("Banco de dados das unidades verificado.")

    def generate_unique_id(self, length=6):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

    async def get_user_unit_id(self, user_id: int) -> str | None:
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT unit_id FROM unit_members WHERE user_id = ?", (user_id,))
            if session := await cursor.fetchone(): return session['unit_id']
        return None
    
    async def create_new_unit(self, interaction: discord.Interaction, unit_name: str):
        log_channel = self.bot.get_channel(UNIT_LOG_CHANNEL_ID)
        if not log_channel:
            await interaction.followup.send("❌ Erro de configuração: Canal de log de unidades não definido.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_FILE) as db:
            new_id = self.generate_unique_id()
            now = discord.utils.utcnow()
            
            # Cria o embed inicial
            embed = discord.Embed(title=f"✅ Unidade Ativa - {unit_name}", description=f"**ID da Unidade:** `{new_id}`", color=discord.Color.green(), timestamp=now)
            embed.add_field(name="Líder", value=interaction.user.mention, inline=False)
            embed.add_field(name="Membros", value=interaction.user.mention, inline=False)
            log_message = await log_channel.send(embed=embed)
            
            # Salva no banco de dados
            await db.execute("INSERT INTO units (unit_id, name, creator_id, created_at, log_message_id) VALUES (?, ?, ?, ?, ?)", (new_id, unit_name, interaction.user.id, now.isoformat(), log_message.id))
            await db.execute("INSERT INTO unit_members (user_id, unit_id) VALUES (?, ?)", (interaction.user.id, new_id))
            await db.commit()
        
        self.logger.info(f"Unidade '{unit_name}' (ID: {new_id}) criada por {interaction.user.display_name}.")
        await interaction.followup.send(MESSAGES.get("SUCCESS_UNIT_CREATED").format(unit_name=unit_name, unit_id=new_id), ephemeral=True)
        await self.update_dashboard_message()

    async def execute_leave_unit(self, member: discord.Member, reason: str) -> tuple[str | None, str | None]:
        unit_id = await self.get_user_unit_id(member.id)
        if not unit_id:
            return None, MESSAGES.get("ERROR_NOT_IN_UNIT")
            
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            unit_info = await (await db.execute("SELECT * FROM units WHERE unit_id = ?", (unit_id,))).fetchone()
            if not unit_info: return None, MESSAGES.get("ERROR_UNIT_NOT_FOUND")
            
            await db.execute("DELETE FROM unit_members WHERE user_id = ?", (member.id,))
            remaining_members_rows = await (await db.execute("SELECT user_id FROM unit_members WHERE unit_id = ?", (unit_id,))).fetchall()
            unit_name = unit_info['name']
            
            if not remaining_members_rows:
                await db.execute("DELETE FROM units WHERE unit_id = ?", (unit_id,))
                await self.update_unit_log_message(unit_id, is_finished=True, reason=reason, unit_info=unit_info)
            else:
                # CORREÇÃO: Atualiza o log da unidade se ainda houver membros
                await self.update_unit_log_message(unit_id, unit_info=unit_info)
            
            await db.commit()
            
        self.logger.info(f"Usuário {member.display_name} saiu da unidade '{unit_name}'.")
        await self.update_dashboard_message()
        return None, MESSAGES.get("SUCCESS_LEAVE_UNIT")

    async def update_unit_log_message(self, unit_id: str, is_finished: bool = False, reason: str = "", unit_info: aiosqlite.Row = None):
        """Função central para criar e atualizar o embed de log da unidade."""
        log_channel = self.bot.get_channel(UNIT_LOG_CHANNEL_ID)
        if not log_channel: return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild: return
        
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            if not unit_info:
                unit_info = await (await db.execute("SELECT * FROM units WHERE unit_id = ?", (unit_id,))).fetchone()
            if not unit_info: return

            members_rows = await (await db.execute("SELECT user_id FROM unit_members WHERE unit_id = ?", (unit_id,))).fetchall()

        if is_finished:
            embed = discord.Embed(title=f"❌ Unidade Finalizada - {unit_info['name']}", description=f"**ID:** `{unit_id}` | **Motivo:** {reason}", color=discord.Color.red())
            creator = guild.get_member(unit_info['creator_id'])
            embed.add_field(name="Líder", value=creator.mention if creator else "N/A", inline=False)
            embed.set_footer(text=f"Finalizada em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        else:
            embed = discord.Embed(title=f"✅ Unidade Ativa - {unit_info['name']}", description=f"**ID da Unidade:** `{unit_id}`", color=discord.Color.green(), timestamp=datetime.fromisoformat(unit_info['created_at']))
            creator = guild.get_member(unit_info['creator_id'])
            embed.add_field(name="Líder", value=creator.mention if creator else "N/A", inline=False)
            member_list = [f"{m.mention}" for row in members_rows if (m := guild.get_member(row['user_id']))]
            embed.add_field(name="Membros", value="\n".join(member_list) or "Nenhum", inline=False)

        try:
            log_message = await log_channel.fetch_message(unit_info['log_message_id'])
            await log_message.edit(embed=embed)
        except discord.NotFound:
            self.logger.warning(f"Mensagem de log da unidade {unit_id} não encontrada para edição.")

    async def create_dashboard_embed_from_json(self, guild: discord.Guild) -> discord.Embed | None:
        try:
            with open('dashboard_embed.json', 'r', encoding='utf-8') as f: data = json.load(f)
            color_int = int(data.get('color', '#000000').replace("#", ""), 16)
            embed = discord.Embed(title=data.get('title'), description=data.get('description'), color=color_int, timestamp=discord.utils.utcnow())
            if footer := data.get('footer'): embed.set_footer(text=footer.get('text'), icon_url=footer.get('icon_url'))
            if thumb := data.get('thumbnail'):
                if thumb.get('url'): embed.set_thumbnail(url=thumb.get('url'))
            
            async with aiosqlite.connect(DB_FILE) as db:
                db.row_factory = aiosqlite.Row
                all_units = await (await db.execute("SELECT * FROM units ORDER BY created_at")).fetchall()
                if not all_units:
                    embed.description = data.get("no_units_description", "Nenhuma unidade criada.")
                else:
                    for unit in all_units:
                        members_rows = await (await db.execute("SELECT user_id FROM unit_members WHERE unit_id = ?", (unit['unit_id'],))).fetchall()
                        member_list = [f"{m.mention}" for row in members_rows if (m := guild.get_member(row['user_id']))]
                        embed.add_field(name=f"{unit['name']} (`{unit['unit_id']}`)", value=("\n".join(member_list) or "Sem membros."), inline=True)
            return embed
        except Exception as e:
            self.logger.error(f"ERRO ao criar embed do painel: {e}", exc_info=True)
            return None

    async def update_dashboard_message(self):
        if not DASHBOARD_CHANNEL_ID: return
        try:
            guild = self.bot.get_guild(GUILD_ID)
            channel = guild.get_channel(DASHBOARD_CHANNEL_ID) if guild else None
            if not channel: return
            embed_template_title = "Unidades em Serviço"
            try:
                with open('dashboard_embed.json', 'r', encoding='utf-8') as f:
                    embed_template_title = json.load(f).get('title', embed_template_title)
            except Exception: pass
            async for message in channel.history(limit=50):
                if message.author == self.bot.user and message.embeds and message.embeds[0].title.strip() == embed_template_title.strip():
                    if new_embed := await self.create_dashboard_embed_from_json(guild):
                        await message.edit(embed=new_embed, view=UnitDashboardView(self.bot))
                    break
        except Exception as e:
            self.logger.error(f"Falha ao atualizar o painel de unidades: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        was_in_unit_channel = before.channel and before.channel.id in UNIT_VOICE_CHANNEL_IDS
        is_no_longer_in_unit_channel = not after.channel or after.channel.id not in UNIT_VOICE_CHANNEL_IDS
        if was_in_unit_channel and is_no_longer_in_unit_channel:
            await self.execute_leave_unit(member, "Saída do canal de voz")

    @tasks.loop(minutes=5)
    async def check_expired_units(self):
        twelve_hours_ago = datetime.utcnow() - timedelta(hours=12)
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            units_to_check = await (await db.execute("SELECT * FROM units")).fetchall()
        
        for unit in units_to_check:
            created_at = datetime.fromisoformat(unit['created_at'])
            if created_at.replace(tzinfo=None) < twelve_hours_ago.replace(tzinfo=None):
                guild = self.bot.get_guild(GUILD_ID)
                if not guild: continue
                
                async with aiosqlite.connect(DB_FILE) as db:
                    members_rows = await (await db.execute("SELECT user_id FROM unit_members WHERE unit_id = ?", (unit['unit_id'],))).fetchall()
                
                for row in members_rows:
                    member = guild.get_member(row[0])
                    if member:
                        await self.execute_leave_unit(member, "Unidade expirada por tempo")

    @check_expired_units.before_loop
    async def before_check_expired_units(self):
        await self.bot.wait_until_ready()

    unidades_group = app_commands.Group(name="units", description="Comandos para o sistema de unidades.")

    @unidades_group.command(name="painel", description="Envia o painel de controle das unidades.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def post_dashboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.guild.get_channel(DASHBOARD_CHANNEL_ID)
        if not channel:
            await interaction.followup.send("❌ `DASHBOARD_CHANNEL_ID` não configurado.", ephemeral=True)
            return
        embed = await self.create_dashboard_embed_from_json(interaction.guild)
        if not embed:
            await interaction.followup.send("ERRO: Falha ao criar o embed.", ephemeral=True)
            return
        await channel.send(embed=embed, view=UnitDashboardView(self.bot))
        await interaction.followup.send(f"✅ Painel enviado para {channel.mention}!", ephemeral=True)

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'UnitsCog' devido a configs ausentes.")
        return
    cog = UnitsCog(bot)
    bot.tree.add_command(cog.unidades_group, guild=discord.Object(id=GUILD_ID))
    await bot.add_cog(cog)