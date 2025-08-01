# cogs/status_cog.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle
import json
import logging
from datetime import datetime, timedelta
import psutil
import os
import sys

# --- Carregar Configurações ---
try:
    with open('config_status_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    STATUS_CHANNEL_ID = config.get('STATUS_CHANNEL_ID')
    STORAGE_FILE = config.get('STATUS_MESSAGE_STORAGE_FILE')
    EMBED_COLOR = config.get('EMBED_COLOR', '#FFFFFF')
except (FileNotFoundError, json.JSONDecodeError):
    logging.critical("ERRO CRÍTICO: 'config_status_cog.json' não encontrado ou mal formatado.")
    GUILD_ID, ADMIN_ROLE_ID, STATUS_CHANNEL_ID, STORAGE_FILE, EMBED_COLOR = None, None, None, None, '#FFFFFF'

# --- View (Painel) com o Botão de Atualizar ---
class StatusPanelView(ui.View):
    def __init__(self, status_cog_instance):
        super().__init__(timeout=None)
        self.status_cog = status_cog_instance

    @ui.button(label="Atualizar", style=ButtonStyle.secondary, custom_id="refresh_status_button", emoji="🔄")
    async def refresh_button(self, interaction: discord.Interaction, button: ui.Button):
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not admin_role or admin_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        success = await self.status_cog._update_status_message()
        if success:
            await interaction.followup.send("✅ Painel de status atualizado!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Não foi possível atualizar o painel. Verifique os logs.", ephemeral=True)

# --- Classe do Cog de Status ---
class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger('discord_bot')
        self.start_time = datetime.utcnow()
        self.process = psutil.Process(os.getpid())
        self.commands_executed = 0 # NOVO: Contador de comandos

        self.bot.add_view(StatusPanelView(self))
        self.update_status_loop.start()
        self.logger.info("Cog 'StatusCog' carregado e tarefa de atualização iniciada.")

    # NOVO: Listener para contar comandos executados
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            self.commands_executed += 1

    def cog_unload(self):
        self.update_status_loop.cancel()

    def format_uptime(self, duration: timedelta) -> str:
        days, rem = divmod(int(duration.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        parts = []
        if days > 0: parts.append(f"{days}d")
        if hours > 0: parts.append(f"{hours}h")
        if minutes > 0: parts.append(f"{minutes}m")
        if seconds > 0 or not parts: parts.append(f"{seconds}s")
        return " ".join(parts)

    def get_db_size(self, db_file: str) -> str:
        """Calcula o tamanho de um arquivo de banco de dados e o formata."""
        try:
            size_bytes = os.path.getsize(db_file)
            if size_bytes < 1024:
                return f"{size_bytes} B"
            size_kb = size_bytes / 1024
            if size_kb < 1024:
                return f"{size_kb:.2f} KB"
            size_mb = size_kb / 1024
            return f"{size_mb:.2f} MB"
        except FileNotFoundError:
            return "Não encontrado"
        except Exception:
            return "Erro"

    async def _get_status_embed(self) -> discord.Embed:
        """Coleta os dados e monta o embed de status."""
        latency_ms = round(self.bot.latency * 1000)
        uptime = self.format_uptime(datetime.utcnow() - self.start_time)
        ram_usage_mb = self.process.memory_info().rss / (1024 * 1024)
        cpu_usage_percent = self.process.cpu_percent(interval=0.1)
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        discordpy_version = discord.__version__
        
        # Novas métricas
        cogs_list = list(self.bot.cogs.keys())
        voice_connections = len(self.bot.voice_clients)
        db_size_ponto = self.get_db_size('clock.sqlite')
        db_size_adv = self.get_db_size('advertencias.sqlite')
        db_size_ausencia = self.get_db_size('ausencias.sqlite')

        embed_color_int = int(EMBED_COLOR.replace("#", ""), 16)
        embed = discord.Embed(
            title="📊 Status do Bot",
            description="Informações de desempenho e depuração em tempo real.",
            color=embed_color_int,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="🛰️ Conectividade", value=f"**Latência:** `{latency_ms}ms`", inline=True)
        embed.add_field(name="⏱️ Tempo de Atividade", value=f"**Uptime:** `{uptime}`", inline=True)
        embed.add_field(name="🖥️ Recursos do Host", value=f"**CPU:** `{cpu_usage_percent:.2f}%`\n**RAM:** `{ram_usage_mb:.2f} MB`", inline=True)
        
        embed.add_field(
            name="📈 Atividade do Bot",
            value=f"**Comandos (desde o início):** `{self.commands_executed}`\n**Conexões de Voz:** `{voice_connections}`",
            inline=True
        )
        embed.add_field(
            name="⚙️ Módulos (Cogs)",
            value=f"**Carregados:** `{len(cogs_list)}`\n`{', '.join(cogs_list)}`",
            inline=True
        )
        embed.add_field(
            name="🗃️ Bancos de Dados",
            value=f"**Ponto:** `{db_size_ponto}`\n**Advertências:** `{db_size_adv}`\n**Ausências:** `{db_size_ausencia}`",
            inline=True
        )

        embed.add_field(name="🔧 Versões", value=f"**Python:** `{python_version}`\n**Discord.py:** `{discordpy_version}`", inline=False)
        
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_footer(text=f"Última atualização")

        return embed

    async def _update_status_message(self) -> bool:
        """Função central que busca a mensagem e a atualiza com o novo embed."""
        try:
            with open(STORAGE_FILE, 'r') as f:
                data = json.load(f)
                message_id = data.get("message_id")
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.warning(f"Arquivo '{STORAGE_FILE}' não encontrado. Use /painel_status para criar o painel.")
            return False

        status_channel = self.bot.get_channel(STATUS_CHANNEL_ID)
        if not status_channel:
            self.logger.error(f"Canal de status com ID {STATUS_CHANNEL_ID} não encontrado.")
            return False

        try:
            message = await status_channel.fetch_message(message_id)
            new_embed = await self._get_status_embed()
            await message.edit(embed=new_embed, view=StatusPanelView(self))
            self.logger.info(f"Painel de status (ID: {message_id}) atualizado.")
            return True
        except discord.NotFound:
            self.logger.error(f"A mensagem do painel de status (ID: {message_id}) não foi encontrada. Use /painel_status para recriá-la.")
            return False
        except Exception as e:
            self.logger.error(f"Erro ao atualizar o painel de status: {e}", exc_info=True)
            return False

    @tasks.loop(minutes=5.0)
    async def update_status_loop(self):
        await self._update_status_message()

    @update_status_loop.before_loop
    async def before_update_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="painel_status", description="Envia o painel de status persistente para o canal configurado.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        status_channel = self.bot.get_channel(STATUS_CHANNEL_ID)
        if not status_channel:
            await interaction.followup.send("❌ O canal de status não foi configurado corretamente.", ephemeral=True)
            return

        initial_embed = await self._get_status_embed()
        
        try:
            message = await status_channel.send(embed=initial_embed, view=StatusPanelView(self))
            with open(STORAGE_FILE, 'w') as f:
                json.dump({"message_id": message.id}, f)
            
            self.logger.info(f"Painel de status criado no canal {status_channel.name} com ID: {message.id}")
            await interaction.followup.send(f"✅ Painel de status enviado com sucesso para {status_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Não tenho permissão para enviar mensagens no canal de status.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Erro ao criar o painel de status: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao criar o painel.", ephemeral=True)

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID, STATUS_CHANNEL_ID, STORAGE_FILE]):
        logging.error("Não foi possível carregar 'StatusCog' devido a configs ausentes.")
        return
    await bot.add_cog(StatusCog(bot))