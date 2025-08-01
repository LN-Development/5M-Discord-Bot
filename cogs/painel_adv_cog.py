# cogs/painel_adv_cog.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle
import json
import logging
import aiosqlite
from datetime import datetime, timedelta

# --- Carregar Configurações ---
try:
    with open('config_painel_adv_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    WARNING_SETTINGS = config.get('WARNING_SETTINGS', {})
    PANEL_BUTTONS = config.get('PANEL_BUTTONS', {})
except (FileNotFoundError, json.JSONDecodeError):
    logging.critical("ERRO CRÍTICO: 'config_painel_adv_cog.json' não encontrado ou mal formatado.")
    GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID, PANEL_EMBED_DATA, WARNING_SETTINGS, PANEL_BUTTONS = None, None, None, None, {}, {}

DB_FILE = "advertencias.sqlite"

# --- Modal (Janela) para Aplicar Advertência ---
class WarnModal(ui.Modal):
    def __init__(self, adv_cog_instance, adv_type: str):
        self.adv_cog = adv_cog_instance
        self.adv_type = adv_type
        adv_name = WARNING_SETTINGS.get(adv_type, {}).get('name', 'Advertência')
        super().__init__(title=f"Aplicar {adv_name}")

        self.user_id_input = ui.TextInput(
            label="ID do Usuário a ser advertido",
            placeholder="Cole o ID do usuário aqui (ex: 123456789012345678)",
            required=True,
            min_length=17,
            max_length=20
        )
        self.reason_input = ui.TextInput(
            label="Motivo da Advertência",
            style=discord.TextStyle.paragraph,
            placeholder="Seja detalhado e claro sobre o motivo.",
            required=True,
            max_length=500
        )
        self.add_item(self.user_id_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = int(self.user_id_input.value)
        except ValueError:
            await interaction.response.send_message("❌ O ID do usuário fornecido é inválido. Por favor, insira apenas números.", ephemeral=True)
            return

        member_to_warn = interaction.guild.get_member(user_id)
        if not member_to_warn:
            await interaction.response.send_message("❌ Usuário não encontrado neste servidor. Verifique o ID.", ephemeral=True)
            return
        
        await self.adv_cog._apply_warning_logic(interaction, member_to_warn, self.adv_type, self.reason_input.value)


# --- View (Painel) com os Botões ---
class AdvPanelView(ui.View):
    def __init__(self, adv_cog_instance):
        super().__init__(timeout=None)
        self.adv_cog = adv_cog_instance
        
        style_map = {
            "primary": ButtonStyle.primary, "secondary": ButtonStyle.secondary,
            "success": ButtonStyle.success, "danger": ButtonStyle.danger
        }

        for adv_type, settings in PANEL_BUTTONS.items():
            button = ui.Button(
                label=settings.get('label', adv_type),
                style=style_map.get(settings.get('style', 'secondary'), ButtonStyle.secondary),
                custom_id=f"adv_button_{adv_type}"
            )
            button.callback = self.button_callback
            self.add_item(button)
            
    async def button_callback(self, interaction: discord.Interaction):
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not admin_role or admin_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Você não tem permissão para usar este painel.", ephemeral=True)
            return

        custom_id = interaction.data['custom_id']
        adv_type = custom_id.replace("adv_button_", "")
        
        modal = WarnModal(self.adv_cog, adv_type)
        await interaction.response.send_modal(modal)


# --- Classe do Cog de Advertências ---
class AdvCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger('discord_bot')
        self.bot.add_view(AdvPanelView(self))
        self.check_timed_roles.start()
        self.logger.info("Cog 'AdvCog' carregado e tarefa de verificação de cargos iniciada.")

    async def cog_load(self):
        """Função executada quando o cog é carregado, para criar/atualizar tabelas no DB."""
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS warnings (
                    ipf_id INTEGER PRIMARY KEY, user_id INTEGER, admin_id INTEGER, 
                    adv_type TEXT, reason TEXT, timestamp TEXT,
                    revoked_by_id INTEGER, revoked_at TEXT, revocation_reason TEXT
                )
            ''')
            # Verifica e adiciona as colunas de revogação se não existirem
            cursor = await db.execute("PRAGMA table_info(warnings)")
            columns = [row[1] for row in await cursor.fetchall()]
            if 'revoked_by_id' not in columns:
                await db.execute('ALTER TABLE warnings ADD COLUMN revoked_by_id INTEGER')
                await db.execute('ALTER TABLE warnings ADD COLUMN revoked_at TEXT')
                await db.execute('ALTER TABLE warnings ADD COLUMN revocation_reason TEXT')
                self.logger.info("Colunas de revogação adicionadas à tabela 'warnings'.")

            await db.execute('CREATE TABLE IF NOT EXISTS timed_roles (record_id INTEGER PRIMARY KEY, user_id INTEGER, guild_id INTEGER, role_id INTEGER, remove_at TEXT)')
            await db.commit()
            self.logger.info("Banco de dados de advertências verificado/criado.")

    def cog_unload(self):
        self.check_timed_roles.cancel()

    async def _apply_warning_logic(self, interaction: discord.Interaction, usuario: discord.Member, tipo_adv_value: str, motivo: str):
        adv_settings = WARNING_SETTINGS.get(tipo_adv_value)
        if not adv_settings:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Erro: Configurações para '{tipo_adv_value}' não encontradas.", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Erro: Configurações para '{tipo_adv_value}' não encontradas.", ephemeral=True)
            return

        now = datetime.utcnow()
        ipf_id = None
        
        async with aiosqlite.connect(DB_FILE) as db:
            cursor = await db.execute("INSERT INTO warnings (user_id, admin_id, adv_type, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (usuario.id, interaction.user.id, tipo_adv_value, motivo, now.isoformat()))
            await db.commit()
            ipf_id = cursor.lastrowid

        role_id = adv_settings.get('role_id')
        duration_days = adv_settings.get('duration_days')

        if role_id and duration_days and duration_days > 0:
            role_to_add = interaction.guild.get_role(role_id)
            if role_to_add:
                try:
                    await usuario.add_roles(role_to_add, reason=f"Advertência {adv_settings.get('name')} (IPF: {ipf_id})")
                    remove_at = now + timedelta(days=duration_days)
                    async with aiosqlite.connect(DB_FILE) as db:
                        await db.execute("INSERT INTO timed_roles (user_id, guild_id, role_id, remove_at) VALUES (?, ?, ?, ?)", (usuario.id, interaction.guild.id, role_id, remove_at.isoformat()))
                        await db.commit()
                    self.logger.info(f"Cargo {role_to_add.name} adicionado a {usuario.display_name} por {duration_days} dias.")
                except discord.Forbidden:
                    error_msg = "❌ Erro: Não tenho permissão para adicionar este cargo ao usuário."
                    if interaction.response.is_done(): await interaction.followup.send(error_msg, ephemeral=True)
                    else: await interaction.response.send_message(error_msg, ephemeral=True)
                    return
            else:
                self.logger.warning(f"Cargo com ID {role_id} não encontrado no servidor.")

        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed_color = int(adv_settings.get('embed_color', '#FFFFFF').replace("#", ""), 16)
            embed = discord.Embed(title=f"⚖️ Advertência Aplicada - {adv_settings.get('name')}", color=embed_color, timestamp=now)
            embed.add_field(name="IPF (ID da Punição)", value=f"`{ipf_id}`", inline=False)
            embed.add_field(name="Usuário Advertido", value=f"{usuario.mention} (`{usuario.id}`)", inline=True)
            embed.add_field(name="Aplicado por", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
            embed.add_field(name="Motivo", value=motivo, inline=False)
            embed.set_thumbnail(url=usuario.display_avatar.url)
            embed.set_footer(text=f"ID do Usuário: {usuario.id}")
            await log_channel.send(embed=embed)
        
        msg_confirm = f"✅ Advertência `{adv_settings.get('name')}` aplicada com sucesso a {usuario.mention}. (IPF: `{ipf_id}`)"
        if interaction.response.is_done(): await interaction.followup.send(msg_confirm, ephemeral=True)
        else: await interaction.response.send_message(msg_confirm, ephemeral=True)

    @app_commands.command(name="painel_adv", description="Envia o painel de aplicação de advertências.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_adv(self, interaction: discord.Interaction):
        try:
            if not PANEL_EMBED_DATA:
                await interaction.response.send_message("❌ A configuração para o embed do painel (`PANEL_EMBED`) não foi encontrada.", ephemeral=True)
                return
            embed_data = PANEL_EMBED_DATA.copy()
            if 'color' in embed_data and isinstance(embed_data['color'], str):
                embed_data['color'] = int(embed_data['color'].replace("#", ""), 16)
            embed = discord.Embed.from_dict(embed_data)
            await interaction.channel.send(embed=embed, view=AdvPanelView(self))
            await interaction.response.send_message("✅ Painel enviado!", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Erro ao enviar painel de advertência: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ocorreu um erro ao enviar o painel.", ephemeral=True)

    @app_commands.command(name="advertir", description="[Legado] Aplica uma advertência a um usuário via comando.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    @app_commands.describe(usuario="O membro que receberá a advertência.", tipo_adv="O nível da advertência.", motivo="O motivo detalhado.")
    @app_commands.choices(tipo_adv=[discord.app_commands.Choice(name=v['name'], value=k) for k, v in WARNING_SETTINGS.items()])
    async def advertir(self, interaction: discord.Interaction, usuario: discord.Member, tipo_adv: discord.app_commands.Choice[str], motivo: str):
        await interaction.response.defer(ephemeral=True)
        await self._apply_warning_logic(interaction, usuario, tipo_adv.value, motivo)

    @app_commands.command(name="revogar_adv", description="Revoga uma advertência aplicada a um usuário.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    @app_commands.describe(
        ipf="O IPF (ID da Punição) da advertência a ser revogada.",
        motivo="O motivo para a revogação da advertência."
    )
    async def revogar_adv(self, interaction: discord.Interaction, ipf: int, motivo: str):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM warnings WHERE ipf_id = ?", (ipf,))
            warning_record = await cursor.fetchone()

            if not warning_record:
                await interaction.followup.send(f"❌ Advertência com IPF `{ipf}` não encontrada.", ephemeral=True)
                return
            
            if warning_record['revoked_by_id']:
                revoked_by_user = self.bot.get_user(warning_record['revoked_by_id']) or f"ID {warning_record['revoked_by_id']}"
                await interaction.followup.send(f"ℹ️ Esta advertência já foi revogada por **{revoked_by_user}**.", ephemeral=True)
                return

            now_iso = datetime.utcnow().isoformat()
            await db.execute(
                "UPDATE warnings SET revoked_by_id = ?, revoked_at = ?, revocation_reason = ? WHERE ipf_id = ?",
                (interaction.user.id, now_iso, motivo, ipf)
            )
            
            adv_type = warning_record['adv_type']
            adv_settings = WARNING_SETTINGS.get(adv_type, {})
            role_id_to_remove = adv_settings.get('role_id')

            if role_id_to_remove:
                await db.execute("DELETE FROM timed_roles WHERE user_id = ? AND role_id = ?", (warning_record['user_id'], role_id_to_remove))
                
                member = interaction.guild.get_member(warning_record['user_id'])
                role = interaction.guild.get_role(role_id_to_remove)
                if member and role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason=f"Advertência {ipf} revogada.")
                        self.logger.info(f"Cargo '{role.name}' removido de {member.display_name} devido à revogação da ADV {ipf}.")
                    except discord.Forbidden:
                        self.logger.error(f"Não foi possível remover o cargo de {member.display_name} na revogação (sem permissão).")

            await db.commit()

        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="↩️ Advertência Revogada",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="IPF (ID da Punição)", value=f"`{ipf}`", inline=False)
            embed.add_field(name="Usuário Original", value=f"<@{warning_record['user_id']}>", inline=True)
            embed.add_field(name="Revogado por", value=interaction.user.mention, inline=True)
            embed.add_field(name="Motivo da Revogação", value=motivo, inline=False)
            await log_channel.send(embed=embed)

        await interaction.followup.send(f"✅ Advertência IPF `{ipf}` revogada com sucesso.", ephemeral=True)
        
    @advertir.error
    @revogar_adv.error
    @painel_adv.error
    async def adv_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handler de erro unificado para os comandos deste cog."""
        if isinstance(error, app_commands.MissingRole):
            msg = "❌ Você não tem permissão para usar este comando."
        else:
            self.logger.error(f"Erro inesperado em um comando de advertência: {error}", exc_info=True)
            msg = "Ocorreu um erro inesperado."
        
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @tasks.loop(minutes=1.0)
    async def check_timed_roles(self):
        now_utc_iso = datetime.utcnow().isoformat()
        
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM timed_roles WHERE remove_at <= ?", (now_utc_iso,))
            expired_roles = await cursor.fetchall()

            if not expired_roles:
                return

            self.logger.info(f"Encontrados {len(expired_roles)} cargos temporários para remover.")
            
            for record in expired_roles:
                guild = self.bot.get_guild(record['guild_id'])
                if not guild:
                    self.logger.warning(f"Não foi possível encontrar a guilda com ID {record['guild_id']} para remover cargo.")
                    continue
                
                member = None
                try:
                    member = guild.get_member(record['user_id']) or await guild.fetch_member(record['user_id'])
                except discord.NotFound:
                     self.logger.warning(f"Membro com ID {record['user_id']} não encontrado na guilda para remover cargo.")
                
                role = guild.get_role(record['role_id'])

                if member and role:
                    try:
                        await member.remove_roles(role, reason="Tempo de advertência expirado.")
                        self.logger.info(f"Cargo '{role.name}' removido de '{member.display_name}' (ID: {member.id}).")
                    except discord.Forbidden:
                        self.logger.error(f"Não foi possível remover o cargo '{role.name}' de '{member.display_name}'. Sem permissão.")
                    except discord.HTTPException as e:
                         self.logger.error(f"Erro de HTTP ao remover cargo: {e}")
                
                await db.execute("DELETE FROM timed_roles WHERE record_id = ?", (record['record_id'],))
            
            await db.commit()

    @check_timed_roles.before_loop
    async def before_check_timed_roles(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID, LOG_CHANNEL_ID]):
        logging.error("Não foi possível carregar 'AdvCog' devido a configurações essenciais ausentes em 'config_painel_adv_cog.json'.")
        return
    await bot.add_cog(AdvCog(bot))