# cogs/servicos_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle, TextStyle
import json
import logging
from datetime import datetime

logger = logging.getLogger('discord_bot')

try:
    with open('config_servicos_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    logger.info("Configurações do 'ServicosCog' carregadas com sucesso.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_servicos_cog.json': {e}")
    GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID, PANEL_EMBED_DATA = None, None, None, None

class ServicoModal(ui.Modal, title="Formulário de Solicitação de Serviço"):
    nome_id = ui.TextInput(label="Nome / ID do Solicitante", placeholder="Seu nome ou ID no servidor", required=True)
    unidade = ui.TextInput(label="Unidade/Setor", placeholder="Ex: Delegacia de Repressão a Entorpecentes", required=True)
    solicitacao = ui.TextInput(label="Solicitação", style=TextStyle.paragraph, placeholder="Descreva o que você precisa.", required=True, max_length=1000)
    motivo = ui.TextInput(label="Motivo", style=TextStyle.paragraph, placeholder="Justifique a necessidade do serviço.", required=True, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cog_instance = interaction.client.get_cog('ServicosCog')
        dados_servico = {
            "nome_id": self.nome_id.value,
            "unidade": self.unidade.value,
            "solicitacao": self.solicitacao.value,
            "motivo": self.motivo.value
        }
        await cog_instance._send_request_embed(interaction, dados_servico)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"Ocorreu um erro no Modal de Serviço: {error}", exc_info=True)
        await interaction.followup.send("❌ Ocorreu um erro inesperado ao processar o formulário.", ephemeral=True)

class ServicoPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Solicitar Serviço", style=ButtonStyle.success, custom_id="request_service_button_v3", emoji="📋")
    async def request_service_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ServicoModal())

class ApprovalView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def handle_decision(self, interaction: discord.Interaction, decision: str):
        cog_instance = interaction.client.get_cog('ServicosCog')
        if not await cog_instance._check_admin_role(interaction):
            return

        original_embed = interaction.message.embeds[0]
        status_info = {
            "DEFERIDO": {"text": "✅ DEFERIDO", "color": discord.Color.green()},
            "INDEFERIDO": {"text": "❌ INDEFERIDO", "color": discord.Color.red()}
        }
        info = status_info.get(decision)
        
        new_embed = discord.Embed(
            title=f"Solicitação de Serviço - {info['text']}",
            color=info['color'],
            timestamp=datetime.now()
        )
        for field in original_embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        
        if original_embed.author: new_embed.set_author(name=original_embed.author.name)
        if original_embed.thumbnail: new_embed.set_thumbnail(url=original_embed.thumbnail.url)
        
        new_embed.add_field(name="Analisado por", value=interaction.user.mention, inline=False)
        if original_embed.footer: new_embed.set_footer(text=original_embed.footer.text)
        
        for item in self.children:
            item.disabled = True
        
        await interaction.response.edit_message(embed=new_embed, view=self)
        
        try:
            if original_embed.footer:
                solicitante_id_str = original_embed.footer.text.replace("ID do Solicitante: ", "")
                solicitante = interaction.guild.get_member(int(solicitante_id_str))
                if solicitante:
                    solicitacao_resumo = original_embed.fields[1].value.strip('`')[:50]
                    await solicitante.send(f"Sua solicitação de serviço (`{solicitacao_resumo}...`) foi **{decision.lower()}** por {interaction.user.mention}.")
        except Exception as e:
            logger.warning(f"Não foi possível notificar o solicitante da decisão: {e}")

    @ui.button(label="Deferido", style=ButtonStyle.success, custom_id="approve_service_button_v3")
    async def approve_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_decision(interaction, "DEFERIDO")

    @ui.button(label="Indeferido", style=ButtonStyle.danger, custom_id="deny_service_button_v3")
    async def deny_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_decision(interaction, "INDEFERIDO")

class ServicosCog(commands.Cog, name="ServicosCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(ServicoPanelView())
        self.bot.add_view(ApprovalView())
        logger.info("Cog 'ServicosCog' carregado e Views persistentes registradas.")

    servicos_group = app_commands.Group(name="servicos", description="Comandos para o sistema de serviços.")

    async def _check_admin_role(self, interaction: discord.Interaction) -> bool:
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not admin_role or admin_role not in interaction.user.roles:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            return False
        return True

    async def _send_request_embed(self, interaction: discord.Interaction, dados: dict):
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            logger.error(f"Canal de log para serviços (ID: {LOG_CHANNEL_ID}) não encontrado.")
            await interaction.followup.send("❌ Erro de configuração: O canal de log não foi encontrado.", ephemeral=True)
            return

        now = datetime.now()
        embed = discord.Embed(title="📝 Nova Solicitação de Serviço", description="Uma nova solicitação foi registrada e aguarda análise.", color=0x3498db, timestamp=now)
        embed.set_author(name=f"Solicitado por: {dados['nome_id']}")
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.avatar.url)
        embed.add_field(name="Unidade/Setor", value=dados['unidade'], inline=False)
        embed.add_field(name="Solicitação", value=f"```{dados['solicitacao']}```", inline=False)
        embed.add_field(name="Motivo", value=f"```{dados['motivo']}```", inline=False)
        embed.set_footer(text=f"ID do Solicitante: {interaction.user.id}")

        try:
            await log_channel.send(embed=embed, view=ApprovalView())
            await interaction.followup.send(f"✅ Sua solicitação foi enviada para análise no canal {log_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Erro de permissão. Não consigo enviar mensagens no canal de log.", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro desconhecido ao enviar o embed de solicitação: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao enviar sua solicitação.", ephemeral=True)

    @servicos_group.command(name="painel", description="Envia o painel de solicitação de serviços.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_servicos(self, interaction: discord.Interaction):
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return
        try:
            embed_data = PANEL_EMBED_DATA.copy()
            if 'color' in embed_data and isinstance(embed_data['color'], str):
                embed_data['color'] = int(embed_data['color'].lstrip("#"), 16)
            embed = discord.Embed.from_dict(embed_data)
            await interaction.channel.send(embed=embed, view=ServicoPanelView())
            await interaction.response.send_message("✅ Painel de solicitação de serviços enviado!", ephemeral=True)
        except Exception as e:
            logger.error(f"Falha ao criar e enviar o painel de serviços: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro ao enviar o painel.", ephemeral=True)

    @painel_servicos.error
    async def painel_servicos_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
        else:
            logger.error(f"Erro inesperado no comando '/servicos painel': {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocorreu um erro inesperado.", ephemeral=True)

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'ServicosCog' devido a configs ausentes.")
        return
    
    # Cria a instância do cog e adiciona o grupo de comandos à árvore do bot
    cog = ServicosCog(bot)
    bot.tree.add_command(cog.servicos_group, guild=discord.Object(id=GUILD_ID))
    await bot.add_cog(cog)