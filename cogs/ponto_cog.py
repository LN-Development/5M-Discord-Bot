# cogs/ponto_cog.py
import discord
from discord.ext import commands
from discord.ui import Button, View
from discord import app_commands, ButtonStyle
import datetime
import aiosqlite
import json
import logging

# --- 1. Carregar Configurações ---
try:
    with open('config_ponto.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    logging.critical("ERRO CRÍTICO: O arquivo 'config_ponto.json' não foi encontrado.")
    exit()

GUILD_ID = config.get('GUILD_ID')
STAFF_ROLE_ID = config.get('STAFF_ROLE_ID')
PONTO_ROLE_ID = config.get('PONTO_ROLE_ID')
CLOCK_IN_CHANNEL_ID = config.get('CLOCK_IN_CHANNEL_ID')
PONTO_STATUS_CHANNEL_ID = config.get('PONTO_STATUS_CHANNEL_ID')
PONTO_VOICE_CHANNEL_IDS = config.get('PONTO_VOICE_CHANNEL_IDS', [])
MESSAGES = config.get('MESSAGES', {})

# --- 2. Funções do Banco de Dados e Helpers ---
async def setup_database():
    """Cria e atualiza a tabela 'sessions' se necessário."""
    async with aiosqlite.connect('clock.sqlite') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                staff_name TEXT NOT NULL,
                clock_in_time TEXT NOT NULL,
                clock_out_time TEXT,
                status_message_id INTEGER 
            )
        ''')
        async with db.execute("PRAGMA table_info(sessions)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            if 'status_message_id' not in columns:
                await db.execute('ALTER TABLE sessions ADD COLUMN status_message_id INTEGER')
                logging.info("Coluna 'status_message_id' adicionada ao banco de dados.")
        await db.commit()

async def get_open_session(user_id):
    """Verifica se um usuário tem uma sessão de trabalho aberta."""
    async with aiosqlite.connect('clock.sqlite') as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM sessions WHERE staff_id = ? AND clock_out_time IS NULL", (user_id,)) as cursor:
            return await cursor.fetchone()

async def execute_clock_out(bot: commands.Bot, member: discord.Member) -> tuple[bool, str]:
    """Executa a lógica de clock-out e atualiza a mensagem de status."""
    open_session = await get_open_session(member.id)
    if not open_session:
        return (False, MESSAGES.get('ERROR_NOT_CLOCKED_IN', "Você não está em serviço."))

    now = datetime.datetime.now()
    now_iso = now.isoformat()
    
    async with aiosqlite.connect('clock.sqlite') as db:
        await db.execute("UPDATE sessions SET clock_out_time = ? WHERE session_id = ?", (now_iso, open_session['session_id']))
        await db.commit()

    clock_in_time = datetime.datetime.fromisoformat(open_session['clock_in_time'])
    duration = now - clock_in_time
    h, rem = divmod(int(duration.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    duration_str = f"{h}h, {m}m e {s}s"

    if PONTO_STATUS_CHANNEL_ID and open_session['status_message_id']:
        status_channel = bot.get_channel(PONTO_STATUS_CHANNEL_ID)
        if status_channel:
            try:
                message_to_edit = await status_channel.fetch_message(open_session['status_message_id'])
                
                embed_finished = discord.Embed(
                    title="🔴 Serviço Encerrado",
                    description=f"O serviço de **{member.display_name}** foi finalizado.",
                    color=discord.Color.red()
                )
                embed_finished.add_field(name="Entrada", value=f"<t:{int(clock_in_time.timestamp())}:t>", inline=True)
                embed_finished.add_field(name="Saída", value=f"<t:{int(now.timestamp())}:t>", inline=True)
                embed_finished.add_field(name="Duração Total", value=duration_str, inline=True)
                embed_finished.set_thumbnail(url=member.display_avatar.url)
                
                await message_to_edit.edit(embed=embed_finished, view=None)
            except discord.NotFound:
                logging.warning(f"Não foi possível encontrar a mensagem de status com ID {open_session['status_message_id']} para editar.")
            except Exception as e:
                logging.error(f"Erro ao editar a mensagem de status: {e}", exc_info=True)

    return (True, duration_str)

def create_panel_embed_from_json() -> discord.Embed | None:
    """Cria um embed completo a partir do arquivo 'panel_embed.json'."""
    logger = logging.getLogger('discord_bot')
    try:
        with open('panel_embed.json', 'r', encoding='utf-8') as f:
            data = json.load(f)

        color_hex = data.get('color', '#000000').replace("#", "")
        color_int = int(color_hex, 16)

        embed = discord.Embed(
            title=data.get('title'),
            description=data.get('description'),
            url=data.get('url'),
            color=color_int
        )
        if footer_data := data.get('footer'):
            embed.set_footer(text=footer_data.get('text'), icon_url=footer_data.get('icon_url'))
        if thumb_data := data.get('thumbnail'):
            embed.set_thumbnail(url=thumb_data.get('url'))
        if image_data := data.get('image'):
            embed.set_image(url=image_data.get('url'))
        
        if fields_data := data.get('fields'):
            for field in fields_data:
                embed.add_field(
                    name=field.get('name', 'Campo sem nome'), 
                    value=field.get('value', 'Campo sem valor'), 
                    inline=field.get('inline', False)
                )
        return embed
    except Exception as e:
        logger.error(f"ERRO ao ler ou processar 'panel_embed.json': {e}", exc_info=True)
        return None

# --- 3. View Persistente com os Botões ---
class ClockView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        try:
            with open('panel_embed.json', 'r', encoding='utf-8') as f:
                button_configs = json.load(f).get("buttons", {})
        except (FileNotFoundError, json.JSONDecodeError):
            button_configs = {}

        style_map = {
            "primary": ButtonStyle.primary, "secondary": ButtonStyle.secondary,
            "success": ButtonStyle.success, "danger": ButtonStyle.danger
        }

        clock_in_config = button_configs.get("clock_in", {"label": "Abrir Ponto", "style": "success"})
        clock_in_button = Button(
            label=clock_in_config.get("label"),
            style=style_map.get(clock_in_config.get("style", "success"), ButtonStyle.success),
            emoji=clock_in_config.get("emoji"),
            custom_id="persistent_clock_in"
        )
        clock_in_button.callback = self.clock_in_callback
        self.add_item(clock_in_button)

        clock_out_config = button_configs.get("clock_out", {"label": "Fechar Ponto", "style": "danger"})
        clock_out_button = Button(
            label=clock_out_config.get("label"),
            style=style_map.get(clock_out_config.get("style", "danger"), ButtonStyle.danger),
            emoji=clock_out_config.get("emoji"),
            custom_id="persistent_clock_out"
        )
        clock_out_button.callback = self.clock_out_callback
        self.add_item(clock_out_button)

    async def check_ponto_role(self, interaction: discord.Interaction) -> bool:
        ponto_role = interaction.guild.get_role(PONTO_ROLE_ID)
        if not ponto_role:
            await interaction.response.send_message(MESSAGES.get('ERROR_ROLE_NOT_CONFIGURED'), ephemeral=True)
            return False
        if ponto_role not in interaction.user.roles:
            await interaction.response.send_message(MESSAGES.get('ERROR_NO_PONTO_PERMISSION'), ephemeral=True)
            return False
        return True

    async def clock_in_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self.check_ponto_role(interaction): return

        user_voice_state = interaction.user.voice
        if not user_voice_state or not user_voice_state.channel or user_voice_state.channel.id not in PONTO_VOICE_CHANNEL_IDS:
            allowed_channels = [f"**{interaction.guild.get_channel(cid).name}**" for cid in PONTO_VOICE_CHANNEL_IDS if interaction.guild.get_channel(cid)]
            await interaction.followup.send(MESSAGES.get('ERROR_NOT_IN_VOICE_CHANNEL').format(channel_names=", ".join(allowed_channels) or "N/A"), ephemeral=True)
            return

        if await get_open_session(interaction.user.id):
            await interaction.followup.send(MESSAGES.get('ERROR_ALREADY_CLOCKED_IN'), ephemeral=True)
            return

        now = datetime.datetime.now()
        session_id = None
        async with aiosqlite.connect('clock.sqlite') as db:
            cursor = await db.execute("INSERT INTO sessions (staff_id, staff_name, clock_in_time) VALUES (?, ?, ?)",
                             (interaction.user.id, interaction.user.display_name, now.isoformat()))
            await db.commit()
            session_id = cursor.lastrowid
        
        if PONTO_STATUS_CHANNEL_ID:
            status_channel = self.bot.get_channel(PONTO_STATUS_CHANNEL_ID)
            if status_channel:
                embed_service = discord.Embed(
                    title="🟢 Em Serviço",
                    description=f"**{interaction.user.display_name}** iniciou o serviço.",
                    color=discord.Color.green()
                )
                embed_service.add_field(name="Horário de Entrada", value=f"<t:{int(now.timestamp())}:t>", inline=False)
                embed_service.set_thumbnail(url=interaction.user.display_avatar.url)
                
                status_message = await status_channel.send(embed=embed_service)
                async with aiosqlite.connect('clock.sqlite') as db:
                    await db.execute("UPDATE sessions SET status_message_id = ? WHERE session_id = ?", (status_message.id, session_id))
                    await db.commit()

        await interaction.followup.send(MESSAGES.get('SUCCESS_CLOCK_IN').format(time=now.strftime('%H:%M:%S')), ephemeral=True)

    async def clock_out_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self.check_ponto_role(interaction): return
        
        success, duration_str = await execute_clock_out(self.bot, interaction.user)
        message_template = MESSAGES.get('SUCCESS_CLOCK_OUT') if success else duration_str
        message = message_template.format(duration=duration_str) if success else duration_str
        await interaction.followup.send(message, ephemeral=True)

# --- 4. Classe do Cog ---
class PontoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger('discord_bot')
        self.bot.add_view(ClockView(self.bot))
        self.logger.info("View 'ClockView' persistente registrada.")

    async def cog_load(self):
        await setup_database()
        self.logger.info("Banco de dados do Ponto verificado/configurado.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        was_in_ponto = before.channel and before.channel.id in PONTO_VOICE_CHANNEL_IDS
        is_no_longer_in_ponto = not after.channel or after.channel.id not in PONTO_VOICE_CHANNEL_IDS
        if was_in_ponto and is_no_longer_in_ponto:
            self.logger.info(f"Detectado que {member.display_name} saiu de um canal de ponto. Verificando sessão...")
            success, duration_str = await execute_clock_out(self.bot, member)
            if success:
                try:
                    await member.send(MESSAGES.get('SUCCESS_AUTO_CLOCK_OUT').format(duration=duration_str))
                    self.logger.info(f"Usuário {member.display_name} desconectado automaticamente. Duração: {duration_str}")
                except discord.Forbidden:
                    self.logger.warning(f"Não foi possível enviar DM para {member.display_name} sobre o clock-out.")
                except Exception as e:
                    self.logger.error(f"Erro ao processar clock-out automático para {member.name}: {e}", exc_info=True)

    async def check_staff_permission(self, interaction: discord.Interaction) -> bool:
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
            await interaction.response.send_message(MESSAGES.get('ERROR_NO_COMMAND_PERMISSION', "Sem permissão."), ephemeral=True)
            return False
        return True

    @app_commands.command(name="enviar_painel_ponto", description="Envia o painel de clock-in/out para o canal.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    async def send_panel(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(CLOCK_IN_CHANNEL_ID)
        if not channel: return await interaction.response.send_message(MESSAGES.get('ERROR_CHANNEL_NOT_FOUND'), ephemeral=True)
        
        embed = create_panel_embed_from_json()
        if not embed: return await interaction.response.send_message("ERRO: Falha ao criar o embed a partir do `panel_embed.json`.", ephemeral=True)
        
        await channel.send(embed=embed, view=ClockView(self.bot))
        await interaction.response.send_message(MESSAGES.get('SUCCESS_PANEL_SENT').format(channel_mention=channel.mention), ephemeral=True)

    @app_commands.command(name="verificar_horas", description="Verifica o total de horas de um membro e o status atual.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def staffcheck(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.check_staff_permission(interaction): return

        async with aiosqlite.connect('clock.sqlite') as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT clock_in_time, clock_out_time FROM sessions WHERE staff_id = ?", (member.id,)) as cursor:
                all_sessions = await cursor.fetchall()
        
        if not all_sessions:
            await interaction.response.send_message(MESSAGES.get('INFO_NO_SESSIONS_FOUND', "Nenhuma sessão encontrada.").format(member_mention=member.mention), ephemeral=True)
            return

        total_secs = 0
        current_session_start = None
        for s in all_sessions:
            if s['clock_out_time']:
                total_secs += (datetime.datetime.fromisoformat(s['clock_out_time']) - datetime.datetime.fromisoformat(s['clock_in_time'])).total_seconds()
            else:
                current_session_start = datetime.datetime.fromisoformat(s['clock_in_time'])

        h, rem = divmod(int(total_secs), 3600); m, s = divmod(rem, 60)
        dur_str = f"{h}h, {m}m e {s}s"
        resp_txt = MESSAGES.get('INFO_TOTAL_TIME_HEADER').format(member_mention=member.mention, duration=dur_str)

        if current_session_start:
            sh, srem = divmod(int((datetime.datetime.now() - current_session_start).total_seconds()), 3600); sm, ss = divmod(srem, 60)
            cur_dur_str = f"{sh}h, {sm}m e {ss}s"
            resp_txt += MESSAGES.get('STATUS_ON_DUTY').format(duration=cur_dur_str)
        else:
            resp_txt += MESSAGES.get('STATUS_OFF_DUTY')
        
        await interaction.response.send_message(resp_txt, ephemeral=True)

    @app_commands.command(name="historico", description="Mostra as últimas sessões de trabalho de um membro.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def historico(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.check_staff_permission(interaction): return

        async with aiosqlite.connect('clock.sqlite') as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM sessions WHERE staff_id = ? ORDER BY clock_in_time DESC LIMIT 10", (member.id,)) as cursor:
                sessions = await cursor.fetchall()

        if not sessions:
            await interaction.response.send_message(MESSAGES.get('INFO_NO_SESSIONS_FOUND').format(member_mention=member.mention), ephemeral=True)
            return
            
        embed = discord.Embed(title=MESSAGES.get('HISTORY_EMBED_TITLE').format(member_name=member.display_name), color=discord.Color.green())
        for session in sessions:
            start_time = datetime.datetime.fromisoformat(session['clock_in_time'])
            if session['clock_out_time']:
                end_time = datetime.datetime.fromisoformat(session['clock_out_time'])
                h, rem = divmod(int((end_time - start_time).total_seconds()), 3600); m, s = divmod(rem, 60)
                dur_str = f"{h}h, {m}m e {s}s"
                val = MESSAGES.get('HISTORY_SESSION_OUTPUT').format(end_time=end_time.strftime('%d/%m/%Y %H:%M:%S'), duration=dur_str)
            else:
                val = MESSAGES.get('HISTORY_SESSION_ON_DUTY')
            embed.add_field(name=MESSAGES.get('HISTORY_SESSION_INPUT_TITLE').format(start_time=start_time.strftime('%d/%m/%Y %H:%M:%S')), value=val, inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- 5. Função Setup ---
async def setup(bot: commands.Bot):
    await bot.add_cog(PontoCog(bot))