# cogs/venda_armas_cog.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle, TextStyle
import json
import logging
from datetime import datetime, timedelta
import aiosqlite

logger = logging.getLogger('discord_bot')

# --- Carregamento de Configuração ---
try:
    with open('config_venda_armas_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    NOTIFICATION_CHANNEL_ID = config.get('NOTIFICATION_CHANNEL_ID')
    REGISTRATION_VALIDITY_DAYS = config.get('REGISTRATION_VALIDITY_DAYS', 30)
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    logger.info("Configurações do 'VendaArmasCog' carregadas com sucesso.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_venda_armas_cog.json': {e}")
    GUILD_ID, ADMIN_ROLE_ID, LOG_CHANNEL_ID, NOTIFICATION_CHANNEL_ID, REGISTRATION_VALIDITY_DAYS, PANEL_EMBED_DATA = [None]*6

DB_FILE = "vendas_armas.sqlite"

# --- Componentes de UI (Views e Modals) ---

class VendaArmaModal(ui.Modal, title="Formulário de Venda de Arma"):
    def __init__(self, cog_instance):
        super().__init__()
        self.cog = cog_instance

    identidade = ui.TextInput(label="Identidade (RG) do Comprador", placeholder="Digite o RG do comprador", required=True)
    cpf = ui.TextInput(label="CPF do Comprador", placeholder="Digite o CPF do comprador", required=True)
    certificado_n = ui.TextInput(label="Certificado Nº", placeholder="Número do certificado de registro da arma", required=True)
    n_arma = ui.TextInput(label="Nº da Arma (Série)", placeholder="Número de série da arma vendida", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        dados_venda = {
            "identidade": self.identidade.value,
            "cpf": self.cpf.value,
            "certificado_n": self.certificado_n.value,
            "n_arma": self.n_arma.value,
        }
        await self.cog.register_sale(interaction, dados_venda)

class VendaArmaPanelView(ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance

    @ui.button(label="Registrar Venda", style=ButtonStyle.primary, custom_id="register_sale_button", emoji="🔫")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not (admin_role and admin_role in interaction.user.roles):
            await interaction.response.send_message("❌ Você não tem permissão para registrar vendas.", ephemeral=True)
            return
        await interaction.response.send_modal(VendaArmaModal(self.cog))

# --- Módulo Principal (Cog) ---
class VendaArmasCog(commands.Cog, name="VendaArmasCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(VendaArmaPanelView(self))
        self.check_expirations.start()
        logger.info("Cog 'VendaArmasCog' carregado e Views persistentes registradas.")

    async def cog_load(self):
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sales (
                    sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rg TEXT NOT NULL,
                    cpf TEXT NOT NULL,
                    certificate_no TEXT NOT NULL,
                    weapon_serial TEXT NOT NULL,
                    registrar_id INTEGER NOT NULL,
                    sale_date TEXT NOT NULL,
                    expiration_date TEXT NOT NULL
                )
            ''')
            await db.commit()
        logger.info("Banco de dados de venda de armas verificado/criado.")
    
    def cog_unload(self):
        self.check_expirations.cancel()

    async def register_sale(self, interaction: discord.Interaction, dados: dict):
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            await interaction.followup.send("❌ Erro de configuração: O canal de log não foi encontrado.", ephemeral=True)
            return

        now = datetime.now()
        expiration_date = now + timedelta(days=REGISTRATION_VALIDITY_DAYS)

        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT INTO sales (rg, cpf, certificate_no, weapon_serial, registrar_id, sale_date, expiration_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (dados['identidade'], dados['cpf'], dados['certificado_n'], dados['n_arma'], interaction.user.id, now.isoformat(), expiration_date.isoformat())
            )
            await db.commit()

        embed = discord.Embed(
            title="🔫 Novo Registro de Venda de Arma",
            color=0xe67e22,
            timestamp=now
        )
        embed.set_author(name=f"Registrado por: {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="Identidade (RG)", value=dados['identidade'], inline=True)
        embed.add_field(name="CPF", value=dados['cpf'], inline=True)
        embed.add_field(name="Certificado Nº", value=dados['certificado_n'], inline=True)
        embed.add_field(name="Nº da Arma", value=dados['n_arma'], inline=True)
        embed.add_field(name="Data da Venda", value=f"<t:{int(now.timestamp())}:D>", inline=True)
        embed.add_field(name="Próxima Aquisição", value=f"<t:{int(expiration_date.timestamp())}:D> (<t:{int(expiration_date.timestamp())}:R>)", inline=True)

        try:
            await log_channel.send(embed=embed)
            await interaction.followup.send(f"✅ Venda registrada com sucesso no canal {log_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Erro de permissão. Não consigo enviar mensagens no canal de log.", ephemeral=True)

    @tasks.loop(hours=12)
    async def check_expirations(self):
        await self.bot.wait_until_ready()
        logger.info("Executando verificação de aquisições de armas expiradas...")
        
        notification_channel = self.bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if not notification_channel:
            logger.warning("Canal de notificação de expirações não configurado. Pulando verificação.")
            return

        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM sales WHERE expiration_date <= ?", (now,))
            expired_sales = await cursor.fetchall()
        
        if not expired_sales:
            logger.info("Nenhuma aquisição expirada encontrada.")
            return

        embed = discord.Embed(
            title="🔔 Notificação de Aquisição de Arma Necessária",
            description="Os seguintes registros de arma atingiram o prazo e necessitam de uma nova aquisição para regularização:",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        
        for sale in expired_sales:
            expiration_date = datetime.fromisoformat(sale['expiration_date'])
            registrar = self.bot.get_user(sale['registrar_id'])
            registrar_name = registrar.display_name if registrar else "Desconhecido"
            
            embed.add_field(
                name=f"Registro de Arma (Série: {sale['weapon_serial']})",
                value=f"**CPF do Titular:** {sale['cpf']}\n"
                      f"**Prazo Expirado em:** <t:{int(expiration_date.timestamp())}:D>\n"
                      f"**Venda Registrada por:** {registrar_name}",
                inline=False
            )
            if len(embed.fields) >= 25:
                await notification_channel.send(embed=embed)
                embed.clear_fields()

        if len(embed.fields) > 0:
            await notification_channel.send(embed=embed)

        logger.info(f"{len(expired_sales)} notificações de aquisição enviadas.")

    venda_armas_group = app_commands.Group(name="armas", description="Comandos para o sistema de venda de armas.")

    @venda_armas_group.command(name="painel", description="Envia o painel de registro de venda de armas.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_venda(self, interaction: discord.Interaction):
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return
        
        try:
            embed_data = PANEL_EMBED_DATA.copy()
            if 'color' in embed_data and isinstance(embed_data['color'], str):
                embed_data['color'] = int(embed_data['color'].lstrip("#"), 16)
            
            embed = discord.Embed.from_dict(embed_data)
            await interaction.channel.send(embed=embed, view=VendaArmaPanelView(self))
            await interaction.response.send_message("✅ Painel de venda de armas enviado!", ephemeral=True)
        except Exception as e:
            logger.error(f"Falha ao criar e enviar o painel de venda: {e}", exc_info=True)

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID, LOG_CHANNEL_ID, NOTIFICATION_CHANNEL_ID]):
        logger.error("Não foi possível carregar 'VendaArmasCog' devido a configs ausentes.")
        return
    
    cog = VendaArmasCog(bot)
    bot.tree.add_command(cog.venda_armas_group, guild=discord.Object(id=GUILD_ID))
    await bot.add_cog(cog)