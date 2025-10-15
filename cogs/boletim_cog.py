# cogs/boletim_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle, TextStyle
import json
import logging
from datetime import datetime

# --- Carregar Configurações e Logger ---
logger = logging.getLogger('discord_bot')

try:
    with open('config_boletim_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    logger.info("Configurações do 'BoletimCog' carregadas com sucesso.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_boletim_cog.json': {e}")
    GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID, PANEL_EMBED_DATA = None, None, None, None

# --- Formulário (Modal) para o Boletim Interno ---
class BoletimModal(ui.Modal, title="Boletim Interno - Preenchimento"):
    servicos_diarios = ui.TextInput(
        label="📂 | DOS SERVIÇOS DIÁRIOS",
        style=TextStyle.paragraph,
        placeholder="Descreva as atividades, operações e serviços do dia.",
        required=False,
        max_length=1000
    )
    instrucao = ui.TextInput(
        label="📂 | DA INSTRUÇÃO",
        style=TextStyle.paragraph,
        placeholder="Detalhes sobre treinamentos, cursos e instruções realizadas.",
        required=False,
        max_length=1000
    )
    assuntos_gerais = ui.TextInput(
        label="📂 | DOS ASSUNTOS GERAIS E ADMINISTRATIVOS",
        style=TextStyle.paragraph,
        placeholder="Informações sobre logística, materiais, escalas, etc.",
        required=False,
        max_length=1000
    )
    justica_disciplina = ui.TextInput(
        label="📂 | DA JUSTIÇA E DISCIPLINA",
        style=TextStyle.paragraph,
        placeholder="Informações sobre elogios, punições, advertências, etc.",
        required=False,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cog_instance = interaction.client.get_cog('BoletimCog')

        # Coleta os dados do formulário
        dados_boletim = {
            "servicos_diarios": self.servicos_diarios.value or "Nada a constar.",
            "instrucao": self.instrucao.value or "Nada a constar.",
            "assuntos_gerais": self.assuntos_gerais.value or "Nada a constar.",
            "justica_disciplina": self.justica_disciplina.value or "Nada a constar."
        }
        
        await cog_instance._send_boletim_embed(interaction, dados_boletim)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"Ocorreu um erro no Modal de Boletim: {error}", exc_info=True)
        await interaction.followup.send("❌ Ocorreu um erro inesperado ao processar o formulário.", ephemeral=True)

# --- View (Painel) com o Botão ---
class BoletimPanelView(ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog_instance = cog_instance

    @ui.button(label="Preencher Boletim Interno", style=ButtonStyle.primary, custom_id="fill_boletim_button", emoji="📰")
    async def fill_boletim_button(self, interaction: discord.Interaction, button: ui.Button):
        # Verifica se o usuário tem permissão para usar o botão
        if await self.cog_instance._check_admin_role(interaction):
            await interaction.response.send_modal(BoletimModal())

# --- Módulo Principal (Cog) ---
class BoletimCog(commands.Cog, name="painel_boletim"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(BoletimPanelView(self))
        logger.info("Cog 'BoletimCog' carregado e View persistente registrada.")

    async def _check_admin_role(self, interaction: discord.Interaction) -> bool:
        """Verifica se o usuário tem o cargo de admin. Responde com erro se não tiver."""
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not admin_role or admin_role not in interaction.user.roles:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            return False
        return True

    async def _send_boletim_embed(self, interaction: discord.Interaction, dados: dict):
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            logger.error(f"Canal de log para boletins (ID: {LOG_CHANNEL_ID}) não encontrado.")
            await interaction.followup.send("❌ Erro de configuração: O canal de log não foi encontrado.", ephemeral=True)
            return

        now = datetime.now()
        
        embed = discord.Embed(
            title=f"BOLETIM INTERNO - {now.strftime('%d/%m/%Y')}",
            description="Resumo das atividades e informações diárias.",
            color=0x242429, # Azul escuro
            timestamp=now
        )
        
     
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        # Adiciona os campos com os dados coletados do formulário
        embed.add_field(name="📂 | DOS SERVIÇOS DIÁRIOS:", value=f"```{dados['servicos_diarios']}```", inline=False)
        embed.add_field(name="📂 | DA INSTRUÇÃO:", value=f"```{dados['instrucao']}```", inline=False)
        embed.add_field(name="📂 | DOS ASSUNTOS GERAIS E ADMINSTRATIVOS:", value=f"```{dados['assuntos_gerais']}```", inline=False)
        embed.add_field(name="📂 | DA JUSTIÇA E DISCIPLINA:", value=f"```{dados['justica_disciplina']}```", inline=False)
        
        # Campo de assinatura preenchido automaticamente
        embed.add_field(name="📝 | Assina:", value=f"{interaction.user.mention}", inline=False)

        try:
            await log_channel.send(embed=embed)
            await interaction.followup.send(f"✅ Boletim Interno enviado com sucesso para o canal {log_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            logger.error(f"O bot não tem permissão para enviar mensagens no canal de log {log_channel.name} (ID: {LOG_CHANNEL_ID}).")
            await interaction.followup.send("❌ Erro de permissão. Não consigo enviar mensagens no canal de log.", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro desconhecido ao enviar o embed de boletim: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao enviar o registro.", ephemeral=True)

    @app_commands.command(name="painel_boletim", description="Envia o painel de criação de Boletim Interno.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_boletim(self, interaction: discord.Interaction):
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return
        
        try:
            embed_data = PANEL_EMBED_DATA.copy()
            if 'color' in embed_data and isinstance(embed_data['color'], str):
                embed_data['color'] = int(embed_data['color'].lstrip("#"), 16)
            
            embed = discord.Embed.from_dict(embed_data)
            await interaction.channel.send(embed=embed, view=BoletimPanelView(self))
            await interaction.response.send_message("✅ Painel de boletim enviado!", ephemeral=True)
        except Exception as e:
            logger.error(f"Falha ao criar e enviar o painel de boletim: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro ao enviar o painel.", ephemeral=True)

    @painel_boletim.error
    async def painel_boletim_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            logger.warning(f"Uso negado do '/painel_boletim' por {interaction.user} (sem o cargo de admin).")
            await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
        else:
            logger.error(f"Erro inesperado no comando '/painel_boletim': {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocorreu um erro inesperado.", ephemeral=True)

# --- Função Setup ---
async def setup(bot: commands.Bot):
    """Função que o discord.py chama para carregar o cog."""
    if not all([GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'BoletimCog' devido a configs ausentes (GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID).")
        return
    await bot.add_cog(BoletimCog(bot))