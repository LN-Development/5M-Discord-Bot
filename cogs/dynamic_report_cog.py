# cogs/dynamic_report_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle, TextStyle
import json
import logging
from datetime import datetime

logger = logging.getLogger('discord_bot')

try:
    with open('config_relatorios.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    REPORT_BLUEPRINTS = {bp['id']: bp for bp in config.get('REPORT_BLUEPRINTS', [])}
    logger.info(f"Configurações do 'DynamicReportCog' carregadas. {len(REPORT_BLUEPRINTS)} modelos de relatório encontrados.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_relatorios.json': {e}")
    GUILD_ID, ADMIN_ROLE_ID, REPORT_BLUEPRINTS = None, None, {}

# --- Componentes Dinâmicos ---
class DynamicReportModal(ui.Modal):
    def __init__(self, blueprint: dict):
        super().__init__(title=blueprint.get('modal_title', 'Formulário de Relatório'))
        self.blueprint = blueprint
        self.field_inputs = []

        style_map = {"paragraph": TextStyle.paragraph, "short": TextStyle.short}

        for i, field_data in enumerate(blueprint.get('fields', [])):
            if i >= 5: 
                logger.warning(f"Modelo de relatório '{blueprint['id']}' tem mais de 5 campos. Apenas os 5 primeiros serão usados.")
                break
            
            text_input = ui.TextInput(
                label=field_data.get('label', f'Campo {i+1}'),
                placeholder=field_data.get('placeholder'),
                style=style_map.get(field_data.get('style', 'short'), TextStyle.short),
                required=True
            )
            self.field_inputs.append(text_input)
            self.add_item(text_input)
            
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cog_instance = interaction.client.get_cog('DynamicReportCog')
        await cog_instance.send_report_embed(interaction, self.blueprint, self.field_inputs)

class DynamicReportView(ui.View):
    def __init__(self, blueprint: dict):
        super().__init__(timeout=None)
        self.blueprint = blueprint
        
        button = ui.Button(
            label=self.blueprint['panel'].get('button_label', 'Abrir Relatório'),
            emoji=self.blueprint['panel'].get('button_emoji'),
            style=ButtonStyle.secondary,
            custom_id=f"dynamic_report_button_{self.blueprint['id']}"
        )
        button.callback = self.button_callback
        self.add_item(button)
        
    async def button_callback(self, interaction: discord.Interaction):
        modal = DynamicReportModal(self.blueprint)
        await interaction.response.send_modal(modal)

# --- Módulo Principal (Cog) ---
class DynamicReportCog(commands.Cog, name="DynamicReportCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Adiciona as Views persistentes para cada modelo de relatório
        for bp_id, blueprint in REPORT_BLUEPRINTS.items():
            self.bot.add_view(DynamicReportView(blueprint))
        logger.info(f"{len(REPORT_BLUEPRINTS)} Views de relatório persistentes registradas.")

    async def send_report_embed(self, interaction: discord.Interaction, blueprint: dict, field_inputs: list[ui.TextInput]):
        log_channel_id = blueprint.get('log_channel_id')
        log_channel = self.bot.get_channel(log_channel_id)

        if not log_channel:
            logger.error(f"Canal de log (ID: {log_channel_id}) para o relatório '{blueprint['id']}' não encontrado.")
            await interaction.followup.send("❌ Erro de configuração: Canal de log não encontrado.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Novo {blueprint.get('modal_title', 'Relatório')}",
            color=int(blueprint['panel'].get('color', '#FFFFFF').replace("#",""), 16),
            timestamp=datetime.now()
        )
        embed.set_author(name=f"Relatório enviado por: {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        for text_input in field_inputs:
            embed.add_field(name=text_input.label, value=text_input.value, inline=False)
            
        embed.set_footer(text=f"ID do Usuário: {interaction.user.id}")

        try:
            await log_channel.send(embed=embed)
            await interaction.followup.send(f"✅ Relatório enviado com sucesso para {log_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            logger.error(f"O bot não tem permissão para enviar mensagens no canal de log {log_channel.name} (ID: {log_channel_id}).")
            await interaction.followup.send("❌ Erro de permissão. Não consigo enviar mensagens no canal de log.", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro desconhecido ao enviar o embed de relatório: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao enviar o registro.", ephemeral=True)
    
# --- Função Setup ---
async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'DynamicReportCog' devido a configs ausentes (GUILD_ID, ADMIN_ROLE_ID).")
        return

    # Adiciona a instância do Cog ao bot
    cog = DynamicReportCog(bot)
    await bot.add_cog(cog)

    # --- LÓGICA DE CRIAÇÃO DE COMANDOS ALTERADA ---
    # A criação do grupo de comandos foi removida.
    
    # Cria um comando principal para cada modelo de relatório no JSON
    for bp_id, blueprint in REPORT_BLUEPRINTS.items():
        # Usamos uma função factory para capturar o valor de 'blueprint' corretamente no loop
        def create_callback(bp):
            async def command_callback(interaction: discord.Interaction):
                # Verifica a permissão dentro do comando
                admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
                if not admin_role or admin_role not in interaction.user.roles:
                    await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
                    return
                
                channel = interaction.channel
                embed_data = bp['panel']
                embed = discord.Embed(
                    title=embed_data.get('title'),
                    description=embed_data.get('description'),
                    color=int(embed_data.get('color', '#FFFFFF').replace("#",""), 16)
                )
                await channel.send(embed=embed, view=DynamicReportView(bp))
                await interaction.response.send_message("✅ Painel enviado!", ephemeral=True)
            return command_callback

        # Cria o comando
        new_command = app_commands.Command(
            name=bp_id, # O nome do comando agora é o ID do relatório
            description=f"Envia o painel para '{blueprint['panel'].get('title', bp_id)}'.",
            callback=create_callback(blueprint)
        )
        
        # Adiciona o comando diretamente à árvore de comandos do bot, em vez de a um grupo
        bot.tree.add_command(new_command, guild=discord.Object(id=GUILD_ID))
        logger.info(f"Comando de painel /{bp_id} criado dinamicamente.")