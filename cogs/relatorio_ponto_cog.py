# cogs/relatorio_ponto_cog.py
import discord
from discord.ext import commands
from discord import app_commands
import json
import logging
import aiosqlite
from datetime import datetime, timedelta
import os

# Importações para a nova funcionalidade de gráfico
import pandas as pd
import matplotlib.pyplot as plt

logger = logging.getLogger('discord_bot')

# --- Carregar Configurações ---
try:
    with open('config_relatorio_ponto.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
except (FileNotFoundError, json.JSONDecodeError):
    logger.critical("ERRO CRÍTICO: 'config_relatorio_ponto.json' não encontrado ou mal formatado.")
    GUILD_ID, ADMIN_ROLE_ID = None, None

DB_FILE = "clock.sqlite" # O mesmo banco de dados do ponto_cog

# --- Classe do Cog de Relatórios ---
class RelatorioPontoCog(commands.Cog, name="RelatorioPontoCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger('discord_bot')
        self.logger.info("Cog 'RelatorioPontoCog' carregado.")

    @app_commands.command(name="relatorio_ponto", description="Gera um relatório completo de ponto e um gráfico de atividade para um membro.")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) # Adicionado para robustez
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    @app_commands.describe(
        membro="O membro para o qual o relatório será gerado."
    )
    async def relatorio_ponto(self, interaction: discord.Interaction, membro: discord.Member):
        await interaction.response.defer(ephemeral=True)

        sessions = []
        try:
            async with aiosqlite.connect(DB_FILE) as db:
                db.row_factory = aiosqlite.Row
                query = "SELECT * FROM sessions WHERE staff_id = ? AND clock_out_time IS NOT NULL ORDER BY clock_in_time ASC"
                async with db.execute(query, (membro.id,)) as cursor:
                    sessions_raw = await cursor.fetchall()
                    sessions = [dict(row) for row in sessions_raw]
        except Exception as e:
            self.logger.error(f"Erro ao consultar o banco de dados de ponto: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro ao acessar o banco de dados.", ephemeral=True)
            return

        if not sessions:
            await interaction.followup.send(f"ℹ️ Nenhum registro de ponto encontrado para **{membro.display_name}**.", ephemeral=True)
            return
            
        output_filename = f"relatorio_{membro.id}_{interaction.id}.txt"
        graph_filename = f"grafico_{membro.id}_{interaction.id}.png"
        
        try:
            # --- Bloco de Geração do Relatório de Texto ---
            report_lines = []
            total_duration = timedelta()

            report_lines.append("==================================================")
            report_lines.append(f"  RELATÓRIO DE PONTO COMPLETO - {membro.display_name.upper()}")
            report_lines.append("==================================================")
            report_lines.append("Período de Análise: Todo o histórico")
            report_lines.append(f"ID do Usuário: {membro.id}")
            report_lines.append("-" * 50)
            report_lines.append("\nSESSÕES REGISTRADAS:\n")

            for i, session in enumerate(sessions, 1):
                clock_in = datetime.fromisoformat(session['clock_in_time'])
                clock_out = datetime.fromisoformat(session['clock_out_time'])
                duration = clock_out - clock_in
                total_duration += duration

                h, rem = divmod(int(duration.total_seconds()), 3600)
                m, s = divmod(rem, 60)
                duration_str = f"{h:02d}h {m:02d}m {s:02d}s"
                
                report_lines.append(
                    f"#{i:03d} | Início: {clock_in.strftime('%d/%m/%Y %H:%M:%S')} | Fim: {clock_out.strftime('%d/%m/%Y %H:%M:%S')} | Duração: {duration_str}"
                )

            total_seconds = int(total_duration.total_seconds())
            total_days, day_rem = divmod(total_seconds, 86400)
            total_hours, hour_rem = divmod(day_rem, 3600)
            total_minutes, _ = divmod(hour_rem, 60)
            
            total_duration_str = f"{total_hours}h {total_minutes}m"
            if total_days > 0:
                total_duration_str = f"{total_days} dias, " + total_duration_str

            report_lines.append("\n" + "-" * 50)
            report_lines.append(f"Total de Sessões: {len(sessions)}")
            report_lines.append(f"Tempo Total de Serviço Registrado: {total_duration_str}")
            report_lines.append("==================================================")
            report_lines.append(f"Relatório gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

            report_content = "\n".join(report_lines)

            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(report_content)
            
            # --- Bloco de Geração do Gráfico ---
            try:
                df = pd.DataFrame(sessions)
                df['clock_in_time'] = pd.to_datetime(df['clock_in_time'])
                df['clock_out_time'] = pd.to_datetime(df['clock_out_time'])
                df['duration_hours'] = (df['clock_out_time'] - df['clock_in_time']).dt.total_seconds() / 3600
                
                daily_activity = df.groupby(df['clock_in_time'].dt.date)['duration_hours'].sum()

                plt.style.use('seaborn-v0_8-darkgrid')
                fig, ax = plt.subplots(figsize=(12, 7))
                daily_activity.plot(kind='bar', ax=ax, color='#7289DA', width=0.6)
                ax.set_title(f'Atividade de Ponto Diária - {membro.display_name}', fontsize=16, pad=20)
                ax.set_xlabel('Data', fontsize=12)
                ax.set_ylabel('Total de Horas Trabalhadas', fontsize=12)
                ax.set_xticklabels([d.strftime('%d/%m/%y') for d in daily_activity.index], rotation=45, ha='right')
                ax.grid(axis='y', linestyle='--', alpha=0.7)
                plt.tight_layout()
                plt.savefig(graph_filename)
                plt.close(fig)
                self.logger.info(f"Gráfico de atividade gerado para {membro.display_name}.")
            except Exception as e:
                self.logger.error(f"Falha ao gerar o gráfico de atividade: {e}", exc_info=True)
                graph_filename = None

            # --- Envio dos Arquivos ---
            files_to_send = []
            files_to_send.append(discord.File(output_filename, filename=f"Relatorio_Completo_{membro.name}.txt"))
            if graph_filename and os.path.exists(graph_filename):
                files_to_send.append(discord.File(graph_filename, filename=f"Grafico_Atividade_{membro.name}.png"))

            await interaction.followup.send(
                f"✅ Relatório de ponto e gráfico de atividade para **{membro.display_name}** gerados com sucesso!",
                files=files_to_send,
                ephemeral=True
            )
        except Exception as e:
            self.logger.error(f"Erro ao criar ou enviar o arquivo de relatório: {e}", exc_info=True)
            await interaction.followup.send("❌ Ocorreu um erro ao gerar o arquivo de relatório.", ephemeral=True)
        finally:
            if os.path.exists(output_filename):
                os.remove(output_filename)
            if os.path.exists(graph_filename):
                os.remove(graph_filename)

    @relatorio_ponto.error
    async def relatorio_ponto_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handler de erro para o comando."""
        if isinstance(error, app_commands.MissingRole):
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Você não tem permissão para usar este comando.", ephemeral=True)
        else:
            self.logger.error(f"Erro inesperado no comando /relatorio_ponto: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Ocorreu um erro inesperado.", ephemeral=True)
            else:
                await interaction.followup.send("Ocorreu um erro inesperado.", ephemeral=True)

# --- FUNÇÃO SETUP (ADICIONADA) ---
# Esta função é o ponto de entrada que permite que o init.py carregue este módulo.
async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID]):
        logger.error("Não foi possível carregar 'RelatorioPontoCog' devido a configs ausentes em 'config_relatorio_ponto.json'.")
        return
    await bot.add_cog(RelatorioPontoCog(bot))