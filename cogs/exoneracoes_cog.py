# cogs/exoneracoes_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle, TextStyle
import json
import logging
from datetime import datetime

logger = logging.getLogger('discord_bot')

# --- Carregamento de Configuração ---
try:
    with open('config_exoneracoes_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    logger.info("Configurações do 'ExoneracoesCog' carregadas com sucesso.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_exoneracoes_cog.json': {e}")
    GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID, PANEL_EMBED_DATA = None, None, None, None

# --- Componentes de UI (Views e Modals) ---

class ExoneracaoModal(ui.Modal, title="Formulário de Exoneração"):
    def __init__(self, cog_instance):
        super().__init__()
        self.cog = cog_instance

    nome_exonerado = ui.TextInput(
        label="Nome Completo do Exonerado",
        placeholder="Digite o nome completo do membro.",
        required=True
    )
    id_exonerado = ui.TextInput(
        label="ID do Discord do Exonerado",
        placeholder="Cole o ID de usuário do membro.",
        required=True
    )
    passaporte_exonerado = ui.TextInput(
        label="Passaporte do Exonerado",
        placeholder="Digite o número do passaporte.",
        required=True
    )
    motivo = ui.TextInput(
        label="Motivo da Exoneração",
        style=TextStyle.paragraph,
        placeholder="Descreva detalhadamente o motivo da exoneração.",
        required=True,
        max_length=1024
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        dados_exoneracao = {
            "nome": self.nome_exonerado.value,
            "id": self.id_exonerado.value,
            "passaporte": self.passaporte_exonerado.value,
            "motivo": self.motivo.value
        }
        
        await self.cog.send_exoneracao_embed(interaction, dados_exoneracao)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"Ocorreu um erro no Modal de Exoneração: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Ocorreu um erro inesperado ao processar o formulário.", ephemeral=True)

class ExoneracaoPanelView(ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @ui.button(label="Registrar Exoneração", style=ButtonStyle.danger, custom_id="register_exoneracao_button", emoji="📄")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not (admin_role and admin_role in interaction.user.roles):
            await interaction.response.send_message("❌ Você não tem permissão para registrar exonerações.", ephemeral=True)
            return
        
        await interaction.response.send_modal(ExoneracaoModal(self.cog))

# --- Módulo Principal (Cog) ---
class ExoneracoesCog(commands.Cog, name="ExoneracoesCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(ExoneracaoPanelView(self))
        logger.info("Cog 'ExoneracoesCog' carregado e View persistente registrada.")

    async def send_exoneracao_embed(self, interaction: discord.Interaction, dados: dict):
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            logger.error(f"Canal de log para exonerações (ID: {LOG_CHANNEL_ID}) não encontrado.")
            await interaction.followup.send("❌ Erro de configuração: O canal de log não foi encontrado.", ephemeral=True)
            return

        now = datetime.now()
        
        embed = discord.Embed(
            title="Registro de Exoneração",
            color=0x992d22, # Vermelho escuro
            timestamp=now
        )
        
        embed.set_author(name="Departamento de Recursos Humanos")
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        embed.add_field(name="Nome do Exonerado", value=dados['nome'], inline=False)
        embed.add_field(name="ID", value=f"`{dados['id']}`", inline=True)
        embed.add_field(name="Passaporte", value=f"`{dados['passaporte']}`", inline=True)
        embed.add_field(name="Motivo", value=f"```{dados['motivo']}```", inline=False)
        
        # Campo de assinatura preenchido automaticamente
        embed.add_field(name="Assina", value=interaction.user.mention, inline=False)

        try:
            await log_channel.send(embed=embed)
            await interaction.followup.send(f"✅ Exoneração registrada com sucesso no canal {log_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            logger.error(f"O bot não tem permissão para enviar mensagens no canal de log {log_channel.name} (ID: {LOG_CHANNEL_ID}).")
            await interaction.followup.send("❌ Erro de permissão. Não consigo enviar mensagens no canal de log.", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro desconhecido ao enviar o embed de exoneração: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao enviar o registro.", ephemeral=True)

    # Criação do grupo de comandos de barra
    exoneracao_group = app_commands.Group(name="exoneracao", description="Comandos para o sistema de exonerações.")

    @exoneracao_group.command(name="painel", description="Envia o painel de registro de exonerações.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_exoneracao(self, interaction: discord.Interaction):
        logger.info(f"Comando '/exoneracao painel' executado por: {interaction.user}")
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return
        
        try:
            embed_data = PANEL_EMBED_DATA.copy()
            if 'color' in embed_data and isinstance(embed_data['color'], str):
                embed_data['color'] = int(embed_data['color'].lstrip("#"), 16)
            
            embed = discord.Embed.from_dict(embed_data)
            await interaction.channel.send(embed=embed, view=ExoneracaoPanelView(self))
            await interaction.response.send_message("✅ Painel de exonerações enviado!", ephemeral=True)
        except Exception as e:
            logger.error(f"Falha ao criar e enviar o painel de exonerações: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro ao enviar o painel.", ephemeral=True)

    @painel_exoneracao.error
    async def painel_exoneracao_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
        else:
            logger.error(f"Erro inesperado no comando '/exoneracao painel': {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocorreu um erro inesperado.", ephemeral=True)

# --- Função Setup ---
async def setup(bot: commands.Bot):
    """Função que o discord.py chama para carregar o cog."""
    if not all([GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'ExoneracoesCog' devido a configs ausentes (GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID).")
        return
    
    cog = ExoneracoesCog(bot)
    # Adiciona o grupo de comandos à árvore do bot
    bot.tree.add_command(cog.exoneracao_group, guild=discord.Object(id=GUILD_ID))
    await bot.add_cog(cog)