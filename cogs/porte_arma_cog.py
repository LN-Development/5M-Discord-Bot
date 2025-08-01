# cogs/porte_arma_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle
import json
import logging
from datetime import datetime
import aiosqlite

# --- Carregar Configurações e Logger ---
logger = logging.getLogger('discord_bot')

try:
    with open('config_porte_arma_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('LOG_CHANNEL_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    PANEL_EMBED_DATA = config.get('PANEL_EMBED')
    logger.info("Configurações do 'PorteArmaCog' carregadas com sucesso.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_porte_arma_cog.json': {e}")
    GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID, PANEL_EMBED_DATA = None, None, None, None

DB_FILE = "registros.sqlite"

# --- View para a Etapa 2 do Registro ---
class ContinueRegistrationView(ui.View):
    def __init__(self, dados_parte1: dict):
        super().__init__(timeout=300)
        self.dados_parte1 = dados_parte1
        self.message: discord.WebhookMessage = None

    @ui.button(label="Adicionar Dados da Arma", style=ButtonStyle.success, emoji="➡️")
    async def continue_button(self, interaction: discord.Interaction, button: ui.Button):
        self.stop()
        button.disabled = True
        if self.message:
            await self.message.edit(content="Continuando o registro...", view=self)
        
        modal_parte2 = PorteArmaModalParte2(self.dados_parte1)
        await interaction.response.send_modal(modal_parte2)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⌛ Tempo esgotado para continuar o registro. Por favor, inicie novamente.", view=None)
            except discord.NotFound:
                pass # A mensagem já foi deletada ou não é mais acessível

# --- Formulários (Modals) ---
class PorteArmaModalParte1(ui.Modal, title="Registro de Porte - Dados do Titular"):
    nome_titular = ui.TextInput(label="Nome Completo do Titular", required=True)
    identidade = ui.TextInput(label="Nº da Identidade (RG)", placeholder="Digite o número do documento", required=True)
    cpf = ui.TextInput(label="Nº do CPF", placeholder="Apenas números, sem pontos ou traços", required=True)
    certificado_n = ui.TextInput(label="Certificado Nº", placeholder="Número do certificado de registro", required=True)
    validade = ui.TextInput(label="Validade do Porte (DD/MM/AAAA)", placeholder="Ex: 10/05/2034", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        dados_parte1 = {
            "nome_titular": self.nome_titular.value,
            "identidade": self.identidade.value,
            "cpf": self.cpf.value,
            "certificado_n": self.certificado_n.value,
            "validade": self.validade.value
        }
        
        view = ContinueRegistrationView(dados_parte1)
        message = await interaction.followup.send(
            "✅ **Etapa 1/2 concluída.**\nClique no botão abaixo para adicionar os dados da arma.", 
            view=view, 
            ephemeral=True
        )
        view.message = message

class PorteArmaModalParte2(ui.Modal, title="Registro de Porte - Dados da Arma"):
    def __init__(self, dados_parte1: dict):
        super().__init__()
        self.dados_parte1 = dados_parte1

    n_arma = ui.TextInput(label="Nº de Série da Arma", required=True)
    especie = ui.TextInput(label="Espécie da Arma", placeholder="Ex: Pistola, Revólver, Fuzil", required=True)
    marca = ui.TextInput(label="Marca da Arma", placeholder="Ex: Taurus, Glock, Imbel", required=True)
    calibre = ui.TextInput(label="Calibre da Arma", placeholder="Ex: 9mm, .40, 5.56", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog_instance = interaction.client.get_cog('PorteArmaCog')
        
        dados_parte2 = {
            "n_arma": self.n_arma.value,
            "especie": self.especie.value,
            "marca": self.marca.value,
            "calibre": self.calibre.value
        }
        
        dados_completos = {**self.dados_parte1, **dados_parte2}
        await cog_instance._processar_e_enviar_registro(interaction, dados_completos)

class RevokeModal(ui.Modal, title="Revogar Porte de Arma"):
    def __init__(self, porte_arma_cog_instance, message_id: int):
        super().__init__()
        self.porte_arma_cog = porte_arma_cog_instance
        self.message_id = message_id

    motivo = ui.TextInput(label="Motivo da Revogação", style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.porte_arma_cog._update_porte_status(
            interaction=interaction, message_id=self.message_id, new_status="REVOGADO", reason=self.motivo.value
        )

# --- Views de Controle (Painel Principal e Painel de Log) ---
class PorteArmaPanelView(ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog_instance = cog_instance

    @ui.button(label="Registrar Novo Porte", style=ButtonStyle.success, custom_id="persistent_register_porte_button_v5", emoji="📝")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        if await self.cog_instance._check_admin_role(interaction):
            await interaction.response.send_modal(PorteArmaModalParte1())

class PorteArmaLogView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Revogar", style=ButtonStyle.danger, custom_id="revoke_porte_button_v5", emoji="✖️")
    async def revoke_button(self, interaction: discord.Interaction, button: ui.Button):
        cog_instance = interaction.client.get_cog('PorteArmaCog')
        if await cog_instance._check_admin_role(interaction):
            await interaction.response.send_modal(RevokeModal(cog_instance, interaction.message.id))

    @ui.button(label="Emitir Novamente", style=ButtonStyle.primary, custom_id="reissue_porte_button_v5", emoji="🔄")
    async def reissue_button(self, interaction: discord.Interaction, button: ui.Button):
        cog_instance = interaction.client.get_cog('PorteArmaCog')
        if await cog_instance._check_admin_role(interaction):
            await interaction.response.defer(ephemeral=True)
            await cog_instance._update_porte_status(
                interaction=interaction, message_id=interaction.message.id, new_status="VÁLIDO", reason="Reemitido por"
            )

# --- Módulo Principal (Cog) ---
class PorteArmaCog(commands.Cog, name="PorteArmaCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(PorteArmaPanelView(self))
        self.bot.add_view(PorteArmaLogView())
        logger.info("Cog 'PorteArmaCog' carregado e Views persistentes registradas.")

    async def cog_load(self):
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS portes_arma (
                    id INTEGER PRIMARY KEY, log_message_id INTEGER UNIQUE, status TEXT,
                    nome_titular TEXT, identidade TEXT, cpf TEXT, certificado_n TEXT,
                    n_arma TEXT, especie TEXT, marca TEXT, calibre TEXT, validade TEXT,
                    expedido_por_id INTEGER, expedido_em TEXT,
                    atualizado_por_id INTEGER, atualizado_em TEXT, motivo_atualizacao TEXT
                )
            ''')
            cursor = await db.execute("PRAGMA table_info(portes_arma)")
            columns = [row[1] for row in await cursor.fetchall()]
            required_cols = {'certificado_n', 'especie', 'marca', 'calibre', 'atualizado_por_id', 'atualizado_em', 'motivo_atualizacao'}
            missing_cols = required_cols - set(columns)
            for col in missing_cols:
                await db.execute(f'ALTER TABLE portes_arma ADD COLUMN {col} TEXT')
                logger.info(f"Coluna '{col}' adicionada à tabela 'portes_arma'.")
            await db.commit()
            logger.info("Banco de dados 'portes_arma' verificado/criado.")

    # --- CORREÇÃO APLICADA AQUI ---
    async def _check_admin_role(self, interaction: discord.Interaction) -> bool:
        """Verifica se o usuário tem o cargo de admin. Usa a resposta correta para evitar falhas."""
        admin_role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not admin_role or admin_role not in interaction.user.roles:
            # Se a interação ainda não foi respondida, usa response.send_message
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            # Se já foi respondida (ex: defer), usa followup.send
            else:
                await interaction.followup.send("❌ Você não tem permissão para usar este botão.", ephemeral=True)
            return False
        return True

    def _create_porte_embed(self, record: aiosqlite.Row) -> discord.Embed:
        status_info = {
            "VÁLIDO": {"title": "✅ PORTE DE ARMA VÁLIDO", "color": discord.Color.green()},
            "REVOGADO": {"title": "❌ PORTE DE ARMA REVOGADO", "color": discord.Color.red()}
        }
        current_status = record['status']
        info = status_info.get(current_status, {"title": "PORTE DE ARMA", "color": discord.Color.default()})

        embed = discord.Embed(title=info['title'], color=info['color'], timestamp=datetime.fromisoformat(record['expedido_em']))
        embed.set_author(name="Polícia Federal - Controle de Armamento")

        embed.add_field(name="Nome do Titular", value=record['nome_titular'], inline=False)
        embed.add_field(name="Identidade (RG)", value=record['identidade'], inline=True)
        embed.add_field(name="CPF", value=record['cpf'], inline=True)
        embed.add_field(name="Certificado Nº", value=record['certificado_n'], inline=True)
        embed.add_field(name="Nº da Arma", value=record['n_arma'], inline=True)
        embed.add_field(name="Espécie", value=record['especie'], inline=True)
        embed.add_field(name="Marca", value=record['marca'], inline=True)
        embed.add_field(name="Calibre", value=record['calibre'], inline=True)
        
        validade_dt = datetime.strptime(record['validade'], "%d/%m/%Y")
        embed.add_field(name="Data de Expedição", value=f"<t:{int(datetime.fromisoformat(record['expedido_em']).timestamp())}:D>", inline=True)
        embed.add_field(name="Validade", value=f"<t:{int(validade_dt.timestamp())}:D>", inline=True)
        embed.add_field(name="Expedido por", value=f"<@{record['expedido_por_id']}>", inline=False)

        if current_status == "REVOGADO" and record['atualizado_por_id'] and record['atualizado_em']:
            embed.add_field(
                name=f"Status Atualizado por <@{record['atualizado_por_id']}>",
                value=f"**Ação:** {record['status']}\n"
                      f"**Motivo:** {record['motivo_atualizacao']}\n"
                      f"**Data:** <t:{int(datetime.fromisoformat(record['atualizado_em']).timestamp())}:f>",
                inline=False
            )
        embed.set_footer(text=f"ID do Registro: {record['id']}")
        return embed

    async def _processar_e_enviar_registro(self, interaction: discord.Interaction, dados: dict):
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            await interaction.followup.send("❌ Erro de configuração: Canal de log não encontrado.", ephemeral=True)
            return

        now = datetime.now()
        try:
            datetime.strptime(dados['validade'], "%d/%m/%Y")
        except ValueError:
            await interaction.followup.send(f"❌ Formato de data de validade inválido (`{dados['validade']}`). Use `DD/MM/AAAA`.", ephemeral=True)
            return

        async with aiosqlite.connect(DB_FILE) as db:
            cursor = await db.execute(
                """
                INSERT INTO portes_arma (status, nome_titular, identidade, cpf, certificado_n, n_arma, especie, marca, calibre, validade, expedido_por_id, expedido_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("VÁLIDO", dados['nome_titular'], dados['identidade'], dados['cpf'], dados['certificado_n'], dados['n_arma'], dados['especie'], dados['marca'], dados['calibre'], dados['validade'], interaction.user.id, now.isoformat())
            )
            record_id = cursor.lastrowid
            await db.commit()

            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM portes_arma WHERE id = ?", (record_id,))
            new_record = await cursor.fetchone()

        embed = self._create_porte_embed(new_record)
        log_message = await log_channel.send(embed=embed, view=PorteArmaLogView())

        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("UPDATE portes_arma SET log_message_id = ? WHERE id = ?", (log_message.id, record_id))
            await db.commit()

        await interaction.followup.send(f"✅ Registro enviado com sucesso para {log_channel.mention}!", ephemeral=True)

    async def _update_porte_status(self, interaction: discord.Interaction, message_id: int, new_status: str, reason: str):
        async with aiosqlite.connect(DB_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM portes_arma WHERE log_message_id = ?", (message_id,))
            record = await cursor.fetchone()
            if not record:
                await interaction.followup.send("❌ Registro não encontrado.", ephemeral=True)
                return

            now = datetime.now()
            await db.execute(
                "UPDATE portes_arma SET status = ?, atualizado_por_id = ?, atualizado_em = ?, motivo_atualizacao = ? WHERE log_message_id = ?",
                (new_status, interaction.user.id, now.isoformat(), reason, message_id)
            )
            await db.commit()
            
            cursor = await db.execute("SELECT * FROM portes_arma WHERE log_message_id = ?", (message_id,))
            updated_record = await cursor.fetchone()

        new_embed = self._create_porte_embed(updated_record)
        await interaction.message.edit(embed=new_embed)
        await interaction.followup.send(f"✅ O status do porte foi atualizado para **{new_status}**.", ephemeral=True)

    @app_commands.command(name="painel_porte", description="Envia o painel de registro de porte de arma.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def painel_porte(self, interaction: discord.Interaction):
        if not PANEL_EMBED_DATA:
            await interaction.response.send_message("❌ A configuração do embed do painel não foi encontrada.", ephemeral=True)
            return
        
        embed_data = PANEL_EMBED_DATA.copy()
        if 'color' in embed_data and isinstance(embed_data['color'], str):
            embed_data['color'] = int(embed_data['color'].lstrip("#"), 16)
        
        embed = discord.Embed.from_dict(embed_data)
        await interaction.channel.send(embed=embed, view=PorteArmaPanelView(self))
        await interaction.response.send_message("✅ Painel enviado!", ephemeral=True)

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'PorteArmaCog' devido a configs ausentes.")
        return
    await bot.add_cog(PorteArmaCog(bot))