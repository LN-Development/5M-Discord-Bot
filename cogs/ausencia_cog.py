# cogs/ausencia_cog.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle
import json
import logging
import aiosqlite
from datetime import datetime, timedelta

# --- Carregar Configurações ---
try:
    with open('config_ausencia_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    AUSENTE_ROLE_ID = config.get('AUSENTE_ROLE_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    PANEL_BUTTONS = config.get('PANEL_BUTTONS', {})
except (FileNotFoundError, json.JSONDecodeError):
    logging.critical("ERRO CRÍTICO: 'config_ausencia_cog.json' não encontrado ou mal formatado.")
    GUILD_ID, LOG_CHANNEL_ID, AUSENTE_ROLE_ID, ADMIN_ROLE_ID, PANEL_EMBED_DATA, PANEL_BUTTONS = None, None, None, None, None, {}

DB_FILE = "ausencias.sqlite"

# --- Modal (Formulário) para Registrar Ausência ---
class AusenciaModal(ui.Modal, title="Registrar Período de Ausência"):
    def __init__(self, ausencia_cog_instance):
        super().__init__()
        self.ausencia_cog = ausencia_cog_instance

    data_retorno = ui.TextInput(label="Data de Retorno (DD/MM/AAAA)", placeholder="Exemplo: 31/12/2025", required=True, min_length=10, max_length=10)
    motivo = ui.TextInput(label="Motivo da Ausência", style=discord.TextStyle.paragraph, placeholder="Seja breve e objetivo.", required=True, max_length=200)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data_retorno_str = self.data_retorno.value
        try:
            end_date = datetime.strptime(data_retorno_str, "%d/%m/%Y").replace(hour=23, minute=59, second=59)
            if end_date < datetime.utcnow():
                await interaction.followup.send("❌ A data de retorno não pode ser no passado.", ephemeral=True)
                return
        except ValueError:
            await interaction.followup.send("❌ Formato de data inválido. Use `DD/MM/AAAA`.", ephemeral=True)
            return
        await self.ausencia_cog._apply_ausencia_logic(interaction, end_date, self.motivo.value, data_retorno_str)

# --- View (Painel) com os Botões ---
class AusenciaPanelView(ui.View):
    def __init__(self, ausencia_cog_instance):
        super().__init__(timeout=None)
        self.ausencia_cog = ausencia_cog_instance
        style_map = {"primary": ButtonStyle.primary, "secondary": ButtonStyle.secondary, "success": ButtonStyle.success, "danger": ButtonStyle.danger}

        register_config = PANEL_BUTTONS.get("register", {})
        register_button = ui.Button(label=register_config.get("label", "Registrar Ausência"), style=style_map.get(register_config.get("style", "primary")), emoji=register_config.get("emoji"), custom_id="register_absence_button")
        register_button.callback = self.register_absence_callback
        self.add_item(register_button)

        end_config = PANEL_BUTTONS.get("end", {})
        end_button = ui.Button(label=end_config.get("label", "Encerrar Ausência"), style=style_map.get(end_config.get("style", "danger")), emoji=end_config.get("emoji"), custom_id="end_absence_button")
        end_button.callback = self.end_absence_callback
        self.add_item(end_button)

    async def register_absence_callback(self, interaction: discord.Interaction):
        ausente_role = interaction.guild.get_role(AUSENTE_ROLE_ID)
        if ausente_role and ausente_role in interaction.user.roles:
            await interaction.response.send_message("ℹ️ Você já está registrado como ausente.", ephemeral=True)
            return
        modal = AusenciaModal(self.ausencia_cog)
        await interaction.response.send_modal(modal)

    async def end_absence_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        success = await self.ausencia_cog._end_absence_logic(interaction.user, reason="Retorno antecipado solicitado pelo usuário")
        if success:
            await interaction.followup.send("✅ Sua ausência foi encerrada com sucesso!", ephemeral=True)
        else:
            await interaction.followup.send("ℹ️ Você não está registrado como ausente no momento.", ephemeral=True)

# --- Classe do Cog de Ausência ---
class AusenciaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger('discord_bot')
        self.bot.add_view(AusenciaPanelView(self))
        self.check_ausencias.start()
        self.logger.info("Cog 'AusenciaCog' carregado e tarefa de verificação de ausências iniciada.")

    async def cog_load(self):
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS ausencias (
                    record_id INTEGER PRIMARY KEY, user_id INTEGER, guild_id INTEGER,
                    role_id INTEGER, remove_at TEXT, log_message_id INTEGER
                )
            ''')
            # Verifica e adiciona a nova coluna se não existir
            cursor = await db.execute("PRAGMA table_info(ausencias)")
            columns = [row[1] for row in await cursor.fetchall()]
            if 'log_message_id' not in columns:
                await db.execute('ALTER TABLE ausencias ADD COLUMN log_message_id INTEGER')
                self.logger.info("Coluna 'log_message_id' adicionada à tabela 'ausencias'.")
            await db.commit()
            self.logger.info("Banco de dados de ausências verificado/criado.")

    def cog_unload(self):
        self.check_ausencias.cancel()

    async def _apply_ausencia_logic(self, interaction: discord.Interaction, end_date: datetime, motivo: str, data_retorno_str: str):
        now = datetime.utcnow()
        duration_days = (end_date - now).days + 1
        ausente_role = interaction.guild.get_role(AUSENTE_ROLE_ID)
        if not ausente_role:
            await interaction.followup.send("❌ Erro de configuração: O cargo de ausente não foi encontrado.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(ausente_role, reason=f"Registro de ausência: {motivo}")
            
            log_message_id = None
            log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(title="✈️ Em Ausência", color=discord.Color.orange(), timestamp=now)
                embed.add_field(name="Membro", value=interaction.user.mention, inline=False)
                embed.add_field(name="Período", value=f"{duration_days} dias", inline=True)
                embed.add_field(name="Retorno Previsto", value=f"<t:{int(end_date.timestamp())}:D>", inline=True)
                embed.add_field(name="Motivo", value=motivo, inline=False)
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                log_message = await log_channel.send(embed=embed)
                log_message_id = log_message.id

            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute(
                    "INSERT INTO ausencias (user_id, guild_id, role_id, remove_at, log_message_id) VALUES (?, ?, ?, ?, ?)",
                    (interaction.user.id, interaction.guild.id, AUSENTE_ROLE_ID, end_date.isoformat(), log_message_id)
                )
                await db.commit()
            
            self.logger.info(f"Usuário {interaction.user.display_name} registrou ausência por {duration_days} dias.")
            await interaction.followup.send(f"✅ Sua ausência foi registrada com sucesso! Seu retorno está previsto para **{data_retorno_str}**.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Erro ao aplicar ausência: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado.", ephemeral=True)

    async def _end_absence_logic(self, member: discord.Member, reason: str) -> bool:
        """Lógica central para encerrar uma ausência, remover o cargo e editar o log."""
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM ausencias WHERE user_id = ?", (member.id,))
            record = await cursor.fetchone()
            if not record:
                return False

            await db.execute("DELETE FROM ausencias WHERE record_id = ?", (record['record_id'],))
            await db.commit()
        
        role = member.guild.get_role(AUSENTE_ROLE_ID)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason=reason)
                self.logger.info(f"Cargo de ausente removido de {member.display_name}. Motivo: {reason}")
            except Exception as e:
                self.logger.error(f"Erro ao remover cargo de ausente de {member.display_name}: {e}")

        # --- LÓGICA DE EDIÇÃO DA MENSAGEM ---
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel and record['log_message_id']:
            try:
                log_message = await log_channel.fetch_message(record['log_message_id'])
                original_embed = log_message.embeds[0]
                
                # Cria um novo embed baseado no antigo, mas com informações atualizadas
                embed = discord.Embed(
                    title="✅ Ausência Finalizada",
                    description=f"{member.mention} retornou de seu período de ausência.",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                # Copia campos relevantes do embed original se existirem
                for field in original_embed.fields:
                    embed.add_field(name=field.name, value=field.value, inline=field.inline)
                
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.add_field(name="Status", value=f"Finalizada. ({reason})", inline=False)
                
                await log_message.edit(embed=embed)
            except discord.NotFound:
                self.logger.warning(f"Mensagem de log {record['log_message_id']} não encontrada para editar.")
            except Exception as e:
                self.logger.error(f"Erro ao editar mensagem de log de ausência: {e}", exc_info=True)
        return True

    @app_commands.command(name="painel_ausencia", description="Envia o painel de registro de ausência.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_ausencia(self, interaction: discord.Interaction):
        try:
            if not PANEL_EMBED_DATA:
                await interaction.response.send_message("❌ Configuração do embed do painel não encontrada.", ephemeral=True)
                return
            embed_data = PANEL_EMBED_DATA.copy()
            if 'color' in embed_data and isinstance(embed_data['color'], str):
                embed_data['color'] = int(embed_data['color'].replace("#", ""), 16)
            embed = discord.Embed.from_dict(embed_data)
            await interaction.channel.send(embed=embed, view=AusenciaPanelView(self))
            await interaction.response.send_message("✅ Painel de ausência enviado!", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Erro ao enviar painel de ausência: {e}", exc_info=True)
            await interaction.response.send_message("❌ Ocorreu um erro ao enviar o painel.", ephemeral=True)

    @tasks.loop(minutes=30.0)
    async def check_ausencias(self):
        now_utc_iso = datetime.utcnow().isoformat()
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM ausencias WHERE remove_at <= ?", (now_utc_iso,))
            expired_absences = await cursor.fetchall()
            if not expired_absences: return

            self.logger.info(f"Encontradas {len(expired_absences)} ausências para finalizar.")
            for record in expired_absences:
                guild = self.bot.get_guild(record['guild_id'])
                if not guild: continue
                member = guild.get_member(record['user_id'])
                if member:
                    await self._end_absence_logic(member, reason="Período de ausência finalizado")

    @check_ausencias.before_loop
    async def before_check_ausencias(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, LOG_CHANNEL_ID, AUSENTE_ROLE_ID, ADMIN_ROLE_ID]):
        logging.error("Não foi possível carregar 'AusenciaCog' devido a configs ausentes.")
        return
    await bot.add_cog(AusenciaCog(bot))