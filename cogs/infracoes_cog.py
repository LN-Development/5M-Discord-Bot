# cogs/infracoes_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle, TextStyle
import json
import logging
from datetime import datetime
import aiosqlite

logger = logging.getLogger('discord_bot')

# --- Carregamento de Configuração ---
try:
    with open('config_infracoes_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    logger.info("Configurações do 'InfracoesCog' carregadas com sucesso.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_infracoes_cog.json': {e}")
    GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID, PANEL_EMBED_DATA = None, None, None, None

# --- Componentes de UI (Views e Modals) ---

class InfracaoModal(ui.Modal, title="Formulário de Registro de Infração"):
    def __init__(self, cog_instance):
        super().__init__()
        self.cog = cog_instance

    nome_id_infrator = ui.TextInput(
        label="Nome e ID do Agente",
        placeholder="Forneça o nome completo e, se possível, o ID do Discord.",
        required=True,
        style=TextStyle.short
    )

    relato_fatos = ui.TextInput(
        label="Relato dos Fatos",
        style=TextStyle.paragraph,
        placeholder="Descreva a infração de forma detalhada, incluindo data, hora e local, se aplicável.",
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        dados_infracao = {
            "infrator": self.nome_id_infrator.value,
            "relato": self.relato_fatos.value
        }
        
        await self.cog.send_infracao_embed(interaction, dados_infracao)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"Ocorreu um erro no Modal de Infração: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Ocorreu um erro inesperado ao processar o formulário.", ephemeral=True)

class InfracaoPanelView(ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @ui.button(label="Registrar Infração", style=ButtonStyle.danger, custom_id="register_infracao_button", emoji="⚖️")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        # Verifica se o usuário tem permissão para registrar uma infração
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not (admin_role and admin_role in interaction.user.roles):
            await interaction.response.send_message("❌ Você não tem permissão para registrar uma infração.", ephemeral=True)
            return
        
        await interaction.response.send_modal(InfracaoModal(self.cog))

# --- Módulo Principal (Cog) ---
class InfracoesCog(commands.Cog, name="InfracoesCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(InfracaoPanelView(self))
        logger.info("Cog 'InfracoesCog' carregado e View persistente registrada.")

    async def send_infracao_embed(self, interaction: discord.Interaction, dados: dict):
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            logger.error(f"Canal de log para infrações (ID: {LOG_CHANNEL_ID}) não encontrado.")
            await interaction.followup.send("❌ Erro de configuração: O canal de log não foi encontrado.", ephemeral=True)
            return

        now = datetime.now()
        
        embed = discord.Embed(
            title="⚖️ Novo Registro de Infração",
            color=0xe74c3c, # Vermelho
            timestamp=now
        )
        
        embed.set_author(name=f"Registrado por: {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        
        embed.add_field(name="Nome/ID", value=dados['infrator'], inline=False)
        embed.add_field(name="Relato dos Fatos", value=f"```{dados['relato']}```", inline=False)
        
        embed.set_footer(text=f"ID do Agente: {interaction.user.id}")

        try:
            await log_channel.send(embed=embed)
            await interaction.followup.send(f"✅ Infração registrada com sucesso no canal {log_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            logger.error(f"O bot não tem permissão para enviar mensagens no canal de log {log_channel.name} (ID: {LOG_CHANNEL_ID}).")
            await interaction.followup.send("❌ Erro de permissão. Não consigo enviar mensagens no canal de log.", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro desconhecido ao enviar o embed de infração: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao enviar o registro.", ephemeral=True)

    # Criação do grupo de comandos de barra
    infracao_group = app_commands.Group(name="infracao", description="Comandos para o sistema de registro de infrações.")

    @infracao_group.command(name="enviar", description="Envia o painel de registro de infrações.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_infracao(self, interaction: discord.Interaction):
        logger.info(f"Comando '/infracao painel' executado por: {interaction.user}")
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return
        
        try:
            embed_data = PANEL_EMBED_DATA.copy()
            if 'color' in embed_data and isinstance(embed_data['color'], str):
                embed_data['color'] = int(embed_data['color'].lstrip("#"), 16)
            
            embed = discord.Embed.from_dict(embed_data)
            await interaction.channel.send(embed=embed, view=InfracaoPanelView(self))
            await interaction.response.send_message("✅ Painel de infrações enviado!", ephemeral=True)
        except Exception as e:
            logger.error(f"Falha ao criar e enviar o painel de infrações: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro ao enviar o painel.", ephemeral=True)

    @painel_infracao.error
    async def painel_infracao_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
        else:
            logger.error(f"Erro inesperado no comando '/infracao painel': {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocorreu um erro inesperado.", ephemeral=True)

# --- Função Setup ---
async def setup(bot: commands.Bot):
    """Função que o discord.py chama para carregar o cog."""
    if not all([GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'InfracoesCog' devido a configs ausentes (GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID).")
        return
    
    cog = InfracoesCog(bot)
    # Adiciona o grupo de comandos à árvore do bot
    bot.tree.add_command(cog.infracao_group, guild=discord.Object(id=GUILD_ID))
    await bot.add_cog(cog)