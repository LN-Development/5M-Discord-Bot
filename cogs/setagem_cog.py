# cogs/setagem_cog.py
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
    with open('config_setagem_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    ROLES_TO_ADD = config.get('ROLES_TO_ADD', [])
    logger.info("Configurações do 'SetagemCog' carregadas com sucesso.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_setagem_cog.json': {e}")
    GUILD_ID, ADMIN_ROLE_ID, LOG_CHANNEL_ID, PANEL_EMBED_DATA, ROLES_TO_ADD = None, None, None, None, []

DB_FILE = "setagens.sqlite"

# --- Componentes de UI (Views e Modals) ---

class SetagemModal(ui.Modal, title="Formulário de Solicitação de Setagem"):
    def __init__(self, cog_instance):
        super().__init__()
        self.cog = cog_instance

    nome_completo = ui.TextInput(
        label="Nome Completo para Setagem",
        placeholder="Digite o nome que você usará no servidor.",
        required=True,
        max_length=32,
        style=TextStyle.short,
        row=0
    )

    passaporte = ui.TextInput(
        label="Passaporte do Jogo",
        placeholder="Digite o número do seu passaporte.",
        required=True,
        style=TextStyle.short,
        row=1
    )

    codigo = ui.TextInput(
        label="Código de entrada",
        placeholder="Digite o código.",
        required=True,
        style=TextStyle.short,
        row=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("A processar a sua solicitação...", ephemeral=True)
        self.cog.bot.loop.create_task(
            self.cog.create_setagem_request(
                interaction,
                self.nome_completo.value,
                self.passaporte.value,
                self.codigo.value
            )
        )

class SetagemPanelView(ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @ui.button(label="Solicitar Setagem", style=ButtonStyle.success, custom_id="request_setagem_button", emoji="📝")
    async def request_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SetagemModal(self.cog))

class SetagemApprovalView(ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    async def handle_decision(self, interaction: discord.Interaction, decision: str):
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not (admin_role and admin_role in interaction.user.roles):
            await interaction.response.send_message("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            return

        await interaction.response.defer()

        original_embed = interaction.message.embeds[0]
        try:
            solicitante_id = int(original_embed.footer.text.replace("ID do Solicitante: ", ""))
            novo_nome = next((field.value for field in original_embed.fields if field.name == "Nome Solicitado"), None)
            novo_nome = novo_nome.strip('`') # Remove backticks se existirem
        except (ValueError, IndexError, StopIteration):
            await interaction.followup.send("❌ Não foi possível processar esta solicitação. O embed parece estar corrompido.", ephemeral=True)
            return

        if decision == "ACEITO":
            await self.cog.approve_request(interaction, solicitante_id, novo_nome)
        else:
            await self.cog.deny_request(interaction, solicitante_id)

    @ui.button(label="Aceitar", style=ButtonStyle.success, custom_id="setagem_approve_button")
    async def approve_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_decision(interaction, "ACEITO")

    @ui.button(label="Recusar", style=ButtonStyle.danger, custom_id="setagem_deny_button")
    async def deny_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_decision(interaction, "RECUSADO")

# --- Módulo Principal (Cog) ---
class SetagemCog(commands.Cog, name="SetagemCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(SetagemPanelView(self))
        self.bot.add_view(SetagemApprovalView(self))
        logger.info("Cog 'SetagemCog' carregado e Views persistentes registradas.")

    async def cog_load(self):
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS setagem_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    requested_name TEXT NOT NULL,
                    passaporte TEXT NOT NULL,
                    codigo TEXT NOT NULL,
                    status TEXT NOT NULL,
                    log_message_id INTEGER,
                    processed_by_id INTEGER,
                    created_at TEXT NOT NULL
                )
            ''')
            await db.commit()
        logger.info("Banco de dados de setagens verificado/criado.")

    async def create_setagem_request(self, interaction: discord.Interaction, nome: str, passaporte: str, codigo: str):
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT id FROM setagem_requests WHERE user_id = ? AND status = 'PENDENTE'", (interaction.user.id,)) as cursor:
                if await cursor.fetchone():
                    await interaction.followup.send("⚠️ Você já possui uma solicitação de setagem pendente. Por favor, aguarde a análise.", ephemeral=True)
                    return

        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            logger.error(f"Canal de log de setagens (ID: {LOG_CHANNEL_ID}) não encontrado.")
            await interaction.followup.send("❌ Erro de configuração: O canal de log não foi encontrado. Contate um administrador.", ephemeral=True)
            return

        now = datetime.now()
        embed = discord.Embed(
            title="Nova Solicitação de Setagem",
            description=f"O membro {interaction.user.mention} (`{interaction.user.id}`) solicitou uma nova setagem.",
            color=discord.Color.blue(),
            timestamp=now
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Nome Solicitado", value=f"`{nome}`", inline=False)
        embed.add_field(name="Passaporte", value=f"`{passaporte}`", inline=False)
        embed.add_field(name="Código", value=f"`{codigo}`", inline=False)
        embed.set_footer(text=f"ID do Solicitante: {interaction.user.id}")

        try:
            log_message = await log_channel.send(embed=embed, view=SetagemApprovalView(self))
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute(
                    "INSERT INTO setagem_requests (user_id, requested_name, passaporte, codigo, status, log_message_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (interaction.user.id, nome, passaporte, codigo, "PENDENTE", log_message.id, now.isoformat())
                )
                await db.commit()
            await interaction.followup.send(f"✅ Sua solicitação foi enviada com sucesso para análise!", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro ao enviar solicitação de setagem para {interaction.user.id}: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao enviar sua solicitação. Tente novamente mais tarde.", ephemeral=True)

    async def approve_request(self, interaction: discord.Interaction, solicitante_id: int, novo_nome: str):
        membro = interaction.guild.get_member(solicitante_id)
        if not membro:
            await interaction.followup.send("❌ O membro que fez a solicitação não foi encontrado no servidor.", ephemeral=True)
            return

        try:
            await membro.edit(nick=novo_nome, reason=f"Setagem aprovada por {interaction.user.name}")
            roles_to_add = [interaction.guild.get_role(rid) for rid in ROLES_TO_ADD if rid]
            roles_to_add = [r for r in roles_to_add if r]
            if roles_to_add:
                await membro.add_roles(*roles_to_add, reason=f"Setagem aprovada por {interaction.user.name}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Erro de permissão. Não consigo alterar o apelido ou os cargos deste membro. Verifique minha posição na hierarquia de cargos.", ephemeral=True)
            return
        
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "UPDATE setagem_requests SET status = ?, processed_by_id = ? WHERE log_message_id = ?",
                ("APROVADO", interaction.user.id, interaction.message.id)
            )
            await db.commit()

        original_embed = interaction.message.embeds[0]
        new_embed = discord.Embed.from_dict(original_embed.to_dict())
        new_embed.title = "✅ Solicitação de Setagem Aprovada"
        new_embed.color = discord.Color.green()
        new_embed.add_field(name="Aprovado por", value=interaction.user.mention, inline=False)

        view = ui.View.from_message(interaction.message)
        for item in view.children: item.disabled = True
        await interaction.message.edit(embed=new_embed, view=view)
        await interaction.followup.send("✅ Solicitação aprovada com sucesso!", ephemeral=True)

        try:
            await membro.send(f"Sua solicitação de setagem para o nome **{novo_nome}** foi **APROVADA** por {interaction.user.mention}!")
        except discord.Forbidden:
            logger.warning(f"Não foi possível notificar {membro.name} ({membro.id}) por DM.")

    async def deny_request(self, interaction: discord.Interaction, solicitante_id: int):
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "UPDATE setagem_requests SET status = ?, processed_by_id = ? WHERE log_message_id = ?",
                ("RECUSADO", interaction.user.id, interaction.message.id)
            )
            await db.commit()
            
        original_embed = interaction.message.embeds[0]
        new_embed = discord.Embed.from_dict(original_embed.to_dict())
        new_embed.title = "❌ Solicitação de Setagem Recusada"
        new_embed.color = discord.Color.red()
        new_embed.add_field(name="Recusado por", value=interaction.user.mention, inline=False)
        
        view = ui.View.from_message(interaction.message)
        for item in view.children: item.disabled = True
        await interaction.message.edit(embed=new_embed, view=view)
        await interaction.followup.send("✅ Solicitação recusada com sucesso.", ephemeral=True)

        membro = interaction.guild.get_member(solicitante_id)
        if membro:
            try:
                await membro.send(f"Sua solicitação de setagem foi **RECUSADA** por {interaction.user.mention}.")
            except discord.Forbidden:
                logger.warning(f"Não foi possível notificar {membro.name} ({membro.id}) por DM.")
    
    def _create_panel_embed(self) -> discord.Embed:
        embed_data = PANEL_EMBED_DATA.copy()
        if 'color' in embed_data and isinstance(embed_data['color'], str):
            embed_data['color'] = int(embed_data['color'].lstrip("#"), 16)
        return discord.Embed.from_dict(embed_data)

    # --- Comandos de Barra ---
    
    @app_commands.command(name="enviar_painel_setagem", description="Envia o painel de setagem para um canal específico.")
    @app_commands.describe(canal="O canal de texto para onde o painel será enviado.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def enviar_painel_setagem(self, interaction: discord.Interaction, canal: discord.TextChannel):
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            embed = self._create_panel_embed()
            view = SetagemPanelView(self)
            await canal.send(embed=embed, view=view)
            await interaction.followup.send(f"✅ Painel de setagem enviado com sucesso para o canal {canal.mention}!", ephemeral=True)
        except discord.Forbidden:
            logger.error(f"Sem permissão para enviar mensagem no canal {canal.name} ({canal.id}).")
            await interaction.followup.send(f"❌ Não tenho permissão para enviar mensagens no canal {canal.mention}.", ephemeral=True)
        except Exception as e:
            logger.error(f"Falha ao criar e enviar o painel de setagem: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado ao enviar o painel.", ephemeral=True)

    setagem_group = app_commands.Group(name="setagem", description="Comandos para o sistema de setagem.")

    @setagem_group.command(name="painel", description="Envia o painel de solicitação de setagem no canal atual.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_setagem(self, interaction: discord.Interaction):
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        try:
            embed = self._create_panel_embed()
            view = SetagemPanelView(self)
            await interaction.channel.send(embed=embed, view=view)
            await interaction.followup.send("✅ Painel de setagem enviado!", ephemeral=True)
        except discord.Forbidden:
            logger.error(f"Sem permissão para enviar mensagem no canal {interaction.channel.name} ({interaction.channel.id}).")
            await interaction.followup.send(f"❌ Não tenho permissão para enviar mensagens neste canal.", ephemeral=True)
        except Exception as e:
            logger.error(f"Falha ao criar e enviar o painel de setagem: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro ao enviar o painel.", ephemeral=True)
    
    # --- NOVO COMANDO ---
    @setagem_group.command(name="reenviar", description="Verifica e reenvia solicitações pendentes cuja mensagem foi deletada.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def reenviar_solicitacoes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            await interaction.followup.send("❌ Erro de configuração: O canal de log não foi encontrado.", ephemeral=True)
            return

        checked_count = 0
        resent_count = 0

        try:
            async with aiosqlite.connect(DB_FILE) as db:
                db.row_factory = aiosqlite.Row # Facilita o acesso às colunas por nome
                cursor = await db.execute("SELECT * FROM setagem_requests WHERE status = 'PENDENTE'")
                pending_requests = await cursor.fetchall()

                if not pending_requests:
                    await interaction.followup.send("✅ Nenhuma solicitação pendente encontrada para verificar.", ephemeral=True)
                    return

                for request in pending_requests:
                    checked_count += 1
                    try:
                        await log_channel.fetch_message(request['log_message_id'])
                    except discord.NotFound:
                        # Mensagem não encontrada, precisamos reenviar
                        resent_count += 1
                        logger.info(f"Reenviando solicitação perdida ID: {request['id']} do usuário {request['user_id']}")
                        
                        solicitante = None
                        try:
                            solicitante = await self.bot.fetch_user(request['user_id'])
                        except discord.NotFound:
                             logger.warning(f"Não foi possível encontrar o usuário com ID {request['user_id']} para reenviar a solicitação.")
                             continue # Pula para a próxima solicitação

                        embed = discord.Embed(
                            title="Nova Solicitação de Setagem (Reenviada)",
                            description=f"O membro {solicitante.mention} (`{solicitante.id}`) solicitou uma nova setagem.",
                            color=discord.Color.orange(),
                            timestamp=datetime.fromisoformat(request['created_at'])
                        )
                        embed.set_thumbnail(url=solicitante.display_avatar.url)
                        embed.add_field(name="Nome Solicitado", value=f"`{request['requested_name']}`", inline=False)
                        embed.add_field(name="Passaporte", value=f"`{request['passaporte']}`", inline=False)
                        embed.add_field(name="Código", value=f"`{request['codigo']}`", inline=False)
                        embed.set_footer(text=f"ID do Solicitante: {solicitante.id}")
                        embed.add_field(name="⚠️ Status", value="Esta solicitação foi reenviada pois a mensagem original foi perdida.", inline=False)

                        new_message = await log_channel.send(embed=embed, view=SetagemApprovalView(self))
                        
                        # Atualiza o DB com o ID da nova mensagem
                        await db.execute(
                            "UPDATE setagem_requests SET log_message_id = ? WHERE id = ?",
                            (new_message.id, request['id'])
                        )
                
                await db.commit()

            await interaction.followup.send(
                f"✅ Verificação concluída!\n"
                f"- **{checked_count}** solicitações pendentes verificadas.\n"
                f"- **{resent_count}** solicitações perdidas foram reenviadas com sucesso.",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Erro ao executar o comando /setagem reenviar: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro inesperado durante a verificação. Verifique os logs.", ephemeral=True)


async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID, LOG_CHANNEL_ID]):
        logger.error("Não foi possível carregar 'SetagemCog' devido a configs ausentes.")
        return
    await bot.add_cog(SetagemCog(bot), guilds=[discord.Object(id=GUILD_ID)])