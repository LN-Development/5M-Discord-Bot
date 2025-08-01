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

# --- 1. Carregar Configurações e Mensagens do Cog ---
try:
    with open('config_units.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logging.critical("ERRO CRÍTICO: 'config.json' não foi encontrado.")
    exit()

GUILD_ID = config.get('GUILD_ID')
ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
DASHBOARD_CHANNEL_ID = config.get('DASHBOARD_CHANNEL_ID')
UNIT_VOICE_CHANNEL_IDS = config.get('UNIT_VOICE_CHANNEL_IDS', [])
MESSAGES = config.get('MESSAGES', {})
DB_FILE = "unidades.sqlite"

# --- 2. Modais ---
class CreateUnitModal(Modal, title="Criar Nova Unidade"):
    unit_name = TextInput(label="Nome da Unidade", placeholder="Ex: Equipe Alpha", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('UnitsCog')
        if not cog:
            await interaction.response.send_message("Erro interno: O cog de unidades não foi encontrado.", ephemeral=True)
            return
        if await cog.get_user_unit_id(interaction.user.id):
            await interaction.response.send_message(MESSAGES.get("ERROR_ALREADY_IN_UNIT"), ephemeral=True)
            return
        async with aiosqlite.connect(DB_FILE) as db:
            while True:
                new_id = cog.generate_unique_id()
                async with db.execute("SELECT 1 FROM units WHERE unit_id = ?", (new_id,)) as cursor:
                    if not await cursor.fetchone(): break
            await db.execute("INSERT INTO units (unit_id, name, creator_id, created_at) VALUES (?, ?, ?, ?)", (new_id, str(self.unit_name), interaction.user.id, discord.utils.utcnow().isoformat()))
            await db.execute("INSERT INTO unit_members (user_id, unit_id) VALUES (?, ?)", (interaction.user.id, new_id))
            await db.commit()
        
        cog.logger.info(f"Unidade '{self.unit_name}' (ID: {new_id}) criada por {interaction.user.display_name} (ID: {interaction.user.id}).")
        
        await interaction.response.send_message(MESSAGES.get("SUCCESS_UNIT_CREATED").format(unit_name=self.unit_name, unit_id=new_id), ephemeral=True)
        await cog.update_dashboard_message()

class JoinUnitModal(Modal, title="Entrar em uma Unidade"):
    unit_id_input = TextInput(label="ID da Unidade", placeholder="Insira o ID de 6 caracteres", required=True, min_length=6, max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('UnitsCog')
        if not cog:
            await interaction.response.send_message("Erro interno: O cog de unidades não foi encontrado.", ephemeral=True)
            return
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
        cog.logger.info(f"Usuário {interaction.user.display_name} (ID: {interaction.user.id}) entrou na unidade '{unit[0]}' (ID: {unit_id}).")
        await interaction.response.send_message(MESSAGES.get("SUCCESS_JOIN_UNIT").format(unit_name=unit[0]), ephemeral=True)
        await cog.update_dashboard_message()

# --- 3. View Persistente ---
class UnitDashboardView(View):
    def __init__(self, bot_instance: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.add_item(Button(label="Criar Unidade", style=discord.ButtonStyle.success, custom_id="unit_create", row=0))
        self.add_item(Button(label="Entrar em Unidade", style=discord.ButtonStyle.primary, custom_id="unit_join", row=0))
        self.add_item(Button(label="Sair da Unidade", style=discord.ButtonStyle.danger, custom_id="unit_leave", row=0))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_voice_state = interaction.user.voice
        if not user_voice_state or not user_voice_state.channel or user_voice_state.channel.id not in UNIT_VOICE_CHANNEL_IDS:
            allowed_channels = [f"**{interaction.guild.get_channel(cid).name}**" for cid in UNIT_VOICE_CHANNEL_IDS if interaction.guild.get_channel(cid)]
            channel_list = ", ".join(allowed_channels) if allowed_channels else "Nenhum canal configurado."
            error_msg = MESSAGES.get('ERROR_NOT_IN_VOICE_CHANNEL').format(channel_names=channel_list)
            await interaction.response.send_message(error_msg, ephemeral=True)
            return False
        return True

# --- 4. Classe do Cog de Unidades ---
class UnitsCog(commands.Cog, name="UnitsCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger('discord_bot') 
        self.bot.add_view(UnitDashboardView(self.bot))
        self.check_expired_units.start()
        self.logger.info("Cog de Unidades carregado. View persistente e tarefa em background iniciadas.")

    async def cog_load(self):
        await self.setup_database()

    async def cog_unload(self):
        self.check_expired_units.cancel()
        self.logger.info("Cog de Unidades descarregado. Tarefa em background parada.")

    async def setup_database(self):
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS units (unit_id TEXT PRIMARY KEY, name TEXT NOT NULL, creator_id INTEGER NOT NULL, created_at TEXT NOT NULL)''')
            await db.execute('''CREATE TABLE IF NOT EXISTS unit_members (user_id INTEGER PRIMARY KEY, unit_id TEXT NOT NULL, FOREIGN KEY (unit_id) REFERENCES units (unit_id) ON DELETE CASCADE)''')
            await db.commit()
        self.logger.info("Banco de dados das unidades verificado.")

    def generate_unique_id(self, length=6):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

    async def get_user_unit_id(self, user_id: int) -> str | None:
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT unit_id FROM unit_members WHERE user_id = ?", (user_id,)) as cursor:
                if session := await cursor.fetchone(): return session['unit_id']
            async with db.execute("SELECT unit_id FROM units WHERE creator_id = ?", (user_id,)) as cursor:
                if session := await cursor.fetchone(): return session['unit_id']
        return None

    async def execute_leave_unit(self, member: discord.Member) -> tuple[str | None, str | None]:
        unit_id = await self.get_user_unit_id(member.id)
        if not unit_id:
            return None, MESSAGES.get("ERROR_NOT_IN_UNIT")
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            unit_info = await (await db.execute("SELECT creator_id, name FROM units WHERE unit_id = ?", (unit_id,))).fetchone()
            if not unit_info: return None, MESSAGES.get("ERROR_UNIT_NOT_FOUND")
            creator_id, unit_name = unit_info['creator_id'], unit_info['name']
            await db.execute("DELETE FROM unit_members WHERE user_id = ?", (member.id,))
            if member.id == creator_id:
                remaining_members = await (await db.execute("SELECT 1 FROM unit_members WHERE unit_id = ?", (unit_id,))).fetchone()
                if not remaining_members:
                    self.logger.info(f"Unidade '{unit_name}' (ID: {unit_id}) deletada por ficar vazia após saída do criador {member.display_name} (ID: {member.id}).")
                    await db.execute("DELETE FROM units WHERE unit_id = ?", (unit_id,))
                    await db.commit()
                    return unit_name, MESSAGES.get("UNIT_DELETED_EMPTY").format(unit_name=unit_name)
            await db.commit()
            self.logger.info(f"Usuário {member.display_name} (ID: {member.id}) saiu da unidade '{unit_name}' (ID: {unit_id}).")
            return None, MESSAGES.get("SUCCESS_LEAVE_UNIT")

    async def create_dashboard_embed_from_json(self, guild: discord.Guild) -> discord.Embed | None:
        try:
            with open('dashboard_embed.json', 'r', encoding='utf-8') as f: data = json.load(f)
            color_int = int(data.get('color', '#000000').replace("#", ""), 16)
            embed = discord.Embed(title=data.get('title'), description=data.get('description'), color=color_int, timestamp=discord.utils.utcnow())
            
            # --- INÍCIO DA CORREÇÃO ---
            # As linhas que definem o footer, a thumbnail e a imagem foram restauradas.
            if footer := data.get('footer'): 
                embed.set_footer(text=footer.get('text'), icon_url=footer.get('icon_url'))
            if thumb := data.get('thumbnail'):
                if thumb.get('url'):  # Garante que a URL da thumbnail não seja nula/vazia
                    embed.set_thumbnail(url=thumb.get('url'))
            if image := data.get('image'):
                if image.get('url'): # Garante que a URL da imagem não seja nula/vazia
                    embed.set_image(url=image.get('url'))
            # --- FIM DA CORREÇÃO ---

            async with aiosqlite.connect(DB_FILE) as db:
                db.row_factory = aiosqlite.Row
                all_units = await (await db.execute("SELECT * FROM units ORDER BY created_at")).fetchall()
                if not all_units:
                    embed.description = data.get("no_units_description", "Nenhuma unidade criada.")
                else:
                    for unit in all_units:
                        members_rows = await (await db.execute("SELECT user_id FROM unit_members WHERE unit_id = ?", (unit['unit_id'],))).fetchall()
                        member_list = [f"{m.mention}" for row in members_rows if (m := guild.get_member(row['user_id']))]
                        field_value = "\n".join(member_list) or "Sem membros."
                        embed.add_field(name=f"{unit['name']} (`{unit['unit_id']}`)", value=field_value, inline=True)
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
            embed_template_title = "Unidades em Serviço" # Título padrão
            try:
                with open('dashboard_embed.json', 'r', encoding='utf-8') as f:
                    embed_template_title = json.load(f).get('title', embed_template_title)
            except Exception: pass
            async for message in channel.history(limit=50):
                if message.author == self.bot.user and message.embeds and message.embeds[0].title == embed_template_title:
                    new_embed = await self.create_dashboard_embed_from_json(guild)
                    if new_embed:
                        await message.edit(embed=new_embed, view=UnitDashboardView(self.bot))
                        self.logger.info(f"Painel de unidades atualizado no canal {channel.name}.")
                    break
        except Exception as e:
            self.logger.error(f"Falha ao atualizar o painel de unidades: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component or not interaction.data.get("custom_id"):
            return
        custom_id = interaction.data["custom_id"]
        if custom_id in ["unit_create", "unit_join", "unit_leave"]:
            if not await UnitDashboardView(self.bot).interaction_check(interaction):
                return
        if custom_id == "unit_create":
            await interaction.response.send_modal(CreateUnitModal())
        elif custom_id == "unit_join":
            await interaction.response.send_modal(JoinUnitModal())
        elif custom_id == "unit_leave":
            _, status_message = await self.execute_leave_unit(interaction.user)
            await interaction.response.send_message(status_message, ephemeral=True)
            await self.update_dashboard_message()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        was_in_unit_channel = before.channel and before.channel.id in UNIT_VOICE_CHANNEL_IDS
        is_no_longer_in_unit_channel = not after.channel or after.channel.id not in UNIT_VOICE_CHANNEL_IDS
        if was_in_unit_channel and is_no_longer_in_unit_channel:
            self.logger.info(f"Detectado que {member.display_name} saiu de um canal de unidade. Processando saída...")
            deleted_unit_name, status_message = await self.execute_leave_unit(member)
            if not deleted_unit_name and status_message == MESSAGES.get("SUCCESS_LEAVE_UNIT"):
                try:
                    await member.send(MESSAGES.get("SUCCESS_AUTO_LEAVE_UNIT"))
                    self.logger.info(f"Usuário {member.display_name} removido automaticamente da unidade.")
                except discord.Forbidden:
                    self.logger.warning(f"Não foi possível notificar {member.display_name} sobre a saída automática.")
            await self.update_dashboard_message()

    @tasks.loop(minutes=5)
    async def check_expired_units(self):
        self.logger.info("Executando tarefa de verificação de unidades expiradas...")
        twelve_hours_ago = datetime.now() - timedelta(hours=12)
        units_to_delete = []
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            all_units = await (await db.execute("SELECT unit_id, name, creator_id, created_at FROM units")).fetchall()
            for unit in all_units:
                created_at = datetime.fromisoformat(unit['created_at'].split('.')[0])
                if created_at < twelve_hours_ago:
                    units_to_delete.append(unit)
            if units_to_delete:
                for unit in units_to_delete:
                    await db.execute("DELETE FROM units WHERE unit_id = ?", (unit['unit_id'],))
                await db.commit()
        if units_to_delete:
            guild = self.bot.get_guild(GUILD_ID)
            for unit in units_to_delete:
                creator = guild.get_member(unit['creator_id']) if guild else None
                creator_name = creator.display_name if creator else 'Criador não encontrado'
                self.logger.info(f"Deletando unidade expirada: {unit['name']} ({unit['unit_id']}) criada por {creator_name}.")
                if creator:
                    try:
                        await creator.send(MESSAGES.get("UNIT_DELETED_EXPIRED").format(unit_name=unit['name'], unit_id=unit['unit_id']))
                    except discord.Forbidden:
                        self.logger.warning(f"Não foi possível notificar {creator_name}.")
            await self.update_dashboard_message()

    @check_expired_units.before_loop
    async def before_check_expired_units(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="painel_unidades", description="Envia o painel de controle das unidades.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    async def post_dashboard(self, interaction: discord.Interaction):
        if not DASHBOARD_CHANNEL_ID:
            return await interaction.response.send_message("❌ `DASHBOARD_CHANNEL_ID` não configurado.", ephemeral=True)
        channel = interaction.guild.get_channel(DASHBOARD_CHANNEL_ID)
        if not channel:
            return await interaction.response.send_message(f"❌ Canal com ID {DASHBOARD_CHANNEL_ID} não encontrado.", ephemeral=True)
        embed = await self.create_dashboard_embed_from_json(interaction.guild)
        if not embed:
            return await interaction.response.send_message("ERRO: Falha ao criar o embed. Verifique os logs.", ephemeral=True)
        await channel.send(embed=embed, view=UnitDashboardView(self.bot))
        await interaction.response.send_message(f"✅ Painel enviado para {channel.mention}!", ephemeral=True)

# --- 5. Função Setup para Carregar o Cog ---
async def setup(bot: commands.Bot):
    await bot.add_cog(UnitsCog(bot))