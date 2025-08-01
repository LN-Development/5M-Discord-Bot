# cogs/verificar_promocao_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui, ButtonStyle
import json
import logging
import aiosqlite
import math

logger = logging.getLogger('discord_bot')

try:
    with open('config_verificar_promocao_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    MEMBERS_PER_PAGE = config.get('MEMBERS_PER_PAGE', 10)
    EMBED_COLOR = int(config.get('EMBED_COLOR', '#FFFFFF').replace("#", ""), 16)
    logger.info("Configurações do 'VerificarPromocaoCog' carregadas.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_verificar_promocao_cog.json': {e}")
    GUILD_ID, ADMIN_ROLE_ID, MEMBERS_PER_PAGE, EMBED_COLOR = None, None, 10, 0xFFFFFF

DB_PROMOTION = "promotions.sqlite"

# --- View de Paginação ---
class PromotionListView(ui.View):
    def __init__(self, interaction: discord.Interaction, all_records: list):
        super().__init__(timeout=180) # A view expira após 3 minutos de inatividade
        self.interaction = interaction
        self.all_records = all_records
        self.current_page = 0
        self.total_pages = math.ceil(len(self.all_records) / MEMBERS_PER_PAGE)

    async def create_embed(self) -> discord.Embed:
        """Cria o embed para a página atual."""
        start_index = self.current_page * MEMBERS_PER_PAGE
        end_index = start_index + MEMBERS_PER_PAGE
        records_on_page = self.all_records[start_index:end_index]

        embed = discord.Embed(
            title="👥 Membros no Sistema de Promoção",
            color=EMBED_COLOR,
            description=f"Exibindo {len(records_on_page)} de {len(self.all_records)} membros totais."
        )

        description_lines = []
        for record in records_on_page:
            member = self.interaction.guild.get_member(record['user_id'])
            member_name = member.display_name if member else f"ID: {record['user_id']}"
            
            line = (
                f"**- {member_name}**\n"
                f"  └ **Carreira:** {record['current_carreira_rank']} | "
                f"**Classe:** {record['current_classe_rank']} | "
                f"**Padrão:** {record['current_padrao_rank']}"
            )
            description_lines.append(line)
        
        embed.description += "\n\n" + "\n".join(description_lines)
        embed.set_footer(text=f"Página {self.current_page + 1} de {self.total_pages}")
        
        self._update_buttons()
        return embed

    def _update_buttons(self):
        """Ativa/Desativa os botões de navegação conforme a página atual."""
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == 0
        self.children[2].disabled = self.current_page >= self.total_pages - 1
        self.children[3].disabled = self.current_page >= self.total_pages - 1

    async def update_message(self, interaction: discord.Interaction):
        """Edita a mensagem com o novo embed e a view atualizada."""
        embed = await self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="⏪ Início", style=ButtonStyle.secondary, custom_id="promo_list_first")
    async def go_to_first_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = 0
        await self.update_message(interaction)

    @ui.button(label="◀️ Anterior", style=ButtonStyle.primary, custom_id="promo_list_prev")
    async def go_to_previous_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page -= 1
        await self.update_message(interaction)

    @ui.button(label="Próxima ▶️", style=ButtonStyle.primary, custom_id="promo_list_next")
    async def go_to_next_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page += 1
        await self.update_message(interaction)

    @ui.button(label="Fim ⏩", style=ButtonStyle.secondary, custom_id="promo_list_last")
    async def go_to_last_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = self.total_pages - 1
        await self.update_message(interaction)
        
    async def on_timeout(self):
        # Remove os botões da mensagem quando a view expira
        message = await self.interaction.original_response()
        try:
            await message.edit(view=None)
        except discord.NotFound:
            pass # Mensagem já foi deletada, ignora

# --- Classe do Cog ---
class VerificarPromocaoCog(commands.Cog, name="VerificarPromocaoCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Cog 'VerificarPromocaoCog' carregado.")

    @app_commands.command(name="verificar_promocao", description="Lista todos os membros no sistema de promoção automática.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def verificar_promocao(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PROMOTION) as db:
            db.row_factory = aiosqlite.Row
            # Ordena a lista para uma melhor visualização
            cursor = await db.execute("SELECT * FROM user_promotions ORDER BY current_carreira_rank, current_classe_rank DESC, current_padrao_rank DESC")
            all_records = await cursor.fetchall()
        
        if not all_records:
            await interaction.followup.send("ℹ️ Não há nenhum membro registrado no sistema de promoção no momento.", ephemeral=True)
            return
            
        view = PromotionListView(interaction, all_records)
        initial_embed = await view.create_embed()
        
        await interaction.followup.send(embed=initial_embed, view=view, ephemeral=True)

    @verificar_promocao.error
    async def verificar_promocao_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
        else:
            logger.error(f"Erro inesperado no comando /verificar_promocao: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocorreu um erro inesperado.", ephemeral=True)
            else:
                await interaction.followup.send("Ocorreu um erro inesperado.", ephemeral=True)

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'VerificarPromocaoCog' devido a configs ausentes.")
        return
    await bot.add_cog(VerificarPromocaoCog(bot))