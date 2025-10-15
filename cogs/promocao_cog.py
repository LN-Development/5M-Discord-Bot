# cogs/promocao_cog.py
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui, ButtonStyle
import json
import logging
import aiosqlite
from datetime import datetime, timedelta

logger = logging.getLogger('discord_bot')

try:
    with open('config_promocao_cog.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    GUILD_ID = config.get('GUILD_ID')
    LOG_CHANNEL_ID = config.get('PROMOTION_LOG_CHANNEL_ID')
    ADMIN_ROLE_ID = config.get('ADMIN_ROLE_ID')
    SUPER_ADMIN_ID = config.get('SUPER_ADMIN_ID')
    CARREIRA_ROLES = config.get('CARREIRA_ROLES', {})
    PADRAO_ROLES = {int(k): v for k, v in config.get('PADRAO_ROLES', {}).items()}
    CLASSE_ROLES = config.get('CLASSE_ROLES', {})
    TIME_REQUIREMENTS_SECONDS = {int(k): v * 3600 for k, v in config.get('TIME_REQUIREMENTS_HOURS', {}).items()}
    TIME_REQUIREMENTS_HOURS = config.get('TIME_REQUIREMENTS_HOURS', {})
    logger.info("Configurações do 'PromocaoCog' carregadas.")
except Exception as e:
    logger.critical(f"ERRO CRÍTICO ao carregar 'config_promocao_cog.json': {e}")
    GUILD_ID, LOG_CHANNEL_ID, ADMIN_ROLE_ID, SUPER_ADMIN_ID, CARREIRA_ROLES, PADRAO_ROLES, CLASSE_ROLES, TIME_REQUIREMENTS_SECONDS, TIME_REQUIREMENTS_HOURS = [None]*9

DB_PROMOTION = "promotions.sqlite"
DB_PONTO = "clock.sqlite"

def is_super_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id == SUPER_ADMIN_ID:
            return True
        await interaction.response.send_message("❌ Este comando é restrito ao super administrador do bot.", ephemeral=True)
        return False
    return app_commands.check(predicate)

class PromocaoCog(commands.Cog, name="PromocaoCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.promotion_check_task.start()
        logger.info("Cog 'PromocaoCog' carregado e tarefa de verificação iniciada.")

    async def cog_load(self):
        async with aiosqlite.connect(DB_PROMOTION) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_promotions (
                    user_id INTEGER PRIMARY KEY,
                    current_padrao_rank INTEGER NOT NULL,
                    current_classe_rank TEXT NOT NULL,
                    current_carreira_rank TEXT,
                    ponto_seconds_agente INTEGER DEFAULT 0,
                    ponto_seconds_escrivão INTEGER DEFAULT 0,
                    ponto_seconds_perito INTEGER DEFAULT 0,
                    ponto_seconds_delegado INTEGER DEFAULT 0,
                    last_class_promotion_date TEXT
                )
            ''')
            cursor = await db.execute("PRAGMA table_info(user_promotions)")
            columns = [row[1] for row in await cursor.fetchall()]
            if 'current_carreira_rank' not in columns:
                await db.execute('ALTER TABLE user_promotions ADD COLUMN current_carreira_rank TEXT')
            if 'last_class_promotion_date' not in columns:
                await db.execute('ALTER TABLE user_promotions ADD COLUMN last_class_promotion_date TEXT')
            for carreira_name in CARREIRA_ROLES.keys():
                col_name = f"ponto_seconds_{carreira_name.lower().replace('ã', 'a')}"
                if col_name not in columns:
                    await db.execute(f'ALTER TABLE user_promotions ADD COLUMN {col_name} INTEGER DEFAULT 0')
            await db.commit()
            logger.info("Banco de dados de promoções verificado/criado.")

    def cog_unload(self):
        self.promotion_check_task.cancel()

    def format_seconds(self, seconds: int) -> str:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"

    async def get_total_ponto_seconds(self, user_id: int, since_datetime: datetime = None) -> int:
        total_seconds = 0
        try:
            async with aiosqlite.connect(DB_PONTO) as db:
                db.row_factory = aiosqlite.Row
                
                base_query_closed = "SELECT clock_in_time, clock_out_time FROM sessions WHERE staff_id = ? AND clock_out_time IS NOT NULL"
                base_query_open = "SELECT clock_in_time FROM sessions WHERE staff_id = ? AND clock_out_time IS NULL"
                params = [user_id]
                
                if since_datetime:
                    since_iso = since_datetime.isoformat()
                    base_query_closed += " AND clock_in_time >= ?"
                    base_query_open += " AND clock_in_time >= ?"
                    params.append(since_iso)
                
                cursor = await db.execute(base_query_closed, tuple(params))
                
                closed_sessions = await cursor.fetchall()
                for session in closed_sessions:
                    start = datetime.fromisoformat(session['clock_in_time'])
                    end = datetime.fromisoformat(session['clock_out_time'])
                    total_seconds += (end - start).total_seconds()

                cursor = await db.execute(base_query_open, tuple(params))
                open_session = await cursor.fetchone()
                if open_session:
                    start = datetime.fromisoformat(open_session['clock_in_time'])
                    total_seconds += (datetime.now() - start).total_seconds()
        except Exception as e:
            logger.error(f"Erro ao calcular tempo de ponto para {user_id}: {e}")
        return int(total_seconds)

    async def _handle_class_promotion(self, member: discord.Member, promo_record: aiosqlite.Row):
        guild = member.guild
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        current_class = promo_record['current_classe_rank']
        current_carreira = promo_record['current_carreira_rank']
        class_order = ["Terceira", "Segunda", "Primeira", "Especial"]
        
        try:
            current_index = class_order.index(current_class)
            if current_index + 1 >= len(class_order): return
            next_class = class_order[current_index + 1]
        except ValueError: return

        try:
            role_to_remove_class = guild.get_role(CLASSE_ROLES.get(current_class))
            role_to_add_class = guild.get_role(CLASSE_ROLES.get(next_class))
            role_to_remove_padrao = guild.get_role(PADRAO_ROLES.get(6))
            role_to_add_padrao = guild.get_role(PADRAO_ROLES.get(1))
            roles_to_remove = [r for r in [role_to_remove_class, role_to_remove_padrao] if r]
            roles_to_add = [r for r in [role_to_add_class, role_to_add_padrao] if r]
            
            await member.remove_roles(*roles_to_remove, reason="Promoção de Classe Automática")
            await member.add_roles(*roles_to_add, reason="Promoção de Classe Automática")
            
            async with aiosqlite.connect(DB_PROMOTION) as db:
                time_col_name = f"ponto_seconds_{current_carreira.lower().replace('ã', 'a')}"
                now_iso = datetime.now().isoformat()
                await db.execute(
                    f"UPDATE user_promotions SET current_padrao_rank = 1, current_classe_rank = ?, {time_col_name} = 0, last_class_promotion_date = ? WHERE user_id = ?",
                    (next_class, now_iso, member.id)
                )
                await db.commit()
            
            if log_channel:
                await log_channel.send(f"⬆️ **PROMOÇÃO DE CLASSE AUTOMÁTICA:** {member.mention} foi promovido para **{next_class} Classe**! Seu ciclo de progressão e contagem de horas foram reiniciados.")
        except Exception as e:
            logger.error(f"Erro ao promover classe de {member.display_name}: {e}")

    async def run_promotion_check(self, interaction: discord.Interaction = None):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            if interaction: await interaction.followup.send("❌ Erro: Guilda não encontrada.", ephemeral=True)
            return
            
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        carreira_role_ids = {v['role_id']: k for k, v in CARREIRA_ROLES.items()}
        all_padrao_role_ids = set(PADRAO_ROLES.values())
        all_classe_role_ids = set(CLASSE_ROLES.values())
        
        newly_synced_count, corrected_count, promoted_count = 0, 0, 0

        async with aiosqlite.connect(DB_PROMOTION) as db:
            db.row_factory = aiosqlite.Row
            for member in guild.members:
                if member.bot: continue
                member_role_ids = {r.id for r in member.roles}
                current_carreira = next((name for role_id, name in carreira_role_ids.items() if role_id in member_role_ids), None)
                if not current_carreira: continue
                
                promo_record = await (await db.execute("SELECT * FROM user_promotions WHERE user_id = ?", (member.id,))).fetchone()

                if not promo_record:
                    current_padrao, current_classe = 1, "Terceira"
                    for rank, role_id in sorted(PADRAO_ROLES.items(), reverse=True):
                        if role_id in member_role_ids: current_padrao = rank; break
                    for classe_name, role_id in CLASSE_ROLES.items():
                        if role_id in member_role_ids: current_classe = classe_name; break
                    await db.execute("INSERT INTO user_promotions (user_id, current_padrao_rank, current_classe_rank, current_carreira_rank) VALUES (?, ?, ?, ?)", (member.id, current_padrao, current_classe, current_carreira))
                    await db.commit()
                    logger.info(f"Membro {member.display_name} descoberto com carreira '{current_carreira}' e adicionado ao sistema.")
                    newly_synced_count += 1
                    promo_record = await (await db.execute("SELECT * FROM user_promotions WHERE user_id = ?", (member.id,))).fetchone()

                correct_padrao_rank, correct_classe_rank = promo_record['current_padrao_rank'], promo_record['current_classe_rank']
                correct_padrao_role_id, correct_classe_role_id = PADRAO_ROLES.get(correct_padrao_rank), CLASSE_ROLES.get(correct_classe_rank)
                member_padrao_roles, member_classe_roles = {r.id for r in member.roles if r.id in all_padrao_role_ids}, {r.id for r in member.roles if r.id in all_classe_role_ids}
                needs_correction = (
                    (correct_padrao_role_id not in member_padrao_roles if correct_padrao_role_id else False) or len(member_padrao_roles) > 1 or
                    (correct_classe_role_id not in member_classe_roles if correct_classe_role_id else False) or len(member_classe_roles) > 1
                )
                if needs_correction:
                    logger.warning(f"Detectada inconsistência de cargos para {member.display_name}. Sincronizando...")
                    roles_to_add = [r for r_id in {correct_padrao_role_id, correct_classe_role_id} if (r := guild.get_role(r_id))]
                    roles_to_remove = [guild.get_role(rid) for rid in (member_padrao_roles | member_classe_roles)]
                    roles_to_remove_filtered = [r for r in roles_to_remove if r and r not in roles_to_add]
                    try:
                        if roles_to_remove_filtered: await member.remove_roles(*roles_to_remove_filtered, reason="Sincronização de cargos")
                        if roles_to_add: await member.add_roles(*roles_to_add, reason="Sincronização de cargos")
                        if log_channel: await log_channel.send(f"🔄 **SINCRONIZAÇÃO DE CARGOS:** Os cargos de {member.mention} foram corrigidos para **Padrão {correct_padrao_rank}** e **{correct_classe_rank} Classe**.")
                        corrected_count += 1
                    except Exception as e: logger.error(f"Falha ao sincronizar cargos de {member.display_name}: {e}")
                    continue
                
                since_date_str = promo_record['last_class_promotion_date']
                since_date = datetime.fromisoformat(since_date_str) if since_date_str else None
                total_seconds_in_carreira = await self.get_total_ponto_seconds(member.id, since_date)
                
                time_col_name = f"ponto_seconds_{current_carreira.lower().replace('ã', 'a')}"
                await db.execute(f"UPDATE user_promotions SET {time_col_name} = ? WHERE user_id = ?", (total_seconds_in_carreira, member.id))
                await db.commit()
                
                promo_record = await (await db.execute("SELECT * FROM user_promotions WHERE user_id = ?", (member.id,))).fetchone()
                actual_rank = promo_record['current_padrao_rank']
                
                if actual_rank == 6:
                    max_classe_for_carreira = CARREIRA_ROLES.get(current_carreira, {}).get('max_classe')
                    if max_classe_for_carreira and promo_record['current_classe_rank'] != max_classe_for_carreira:
                        logger.info(f"Membro {member.display_name} (Padrão 6) apto para promoção de classe. Iniciando processo.")
                        await self._handle_class_promotion(member, promo_record)
                    continue

                if actual_rank >= 6: continue
                
                multiplier = CARREIRA_ROLES.get(current_carreira, {}).get('multiplier', 1.0)
                
                correct_rank_by_time = 1
                for rank, base_seconds in sorted(TIME_REQUIREMENTS_SECONDS.items()):
                    if total_seconds_in_carreira >= (base_seconds * multiplier): correct_rank_by_time = rank
                    else: break
                if correct_rank_by_time > 6: correct_rank_by_time = 6
                
                if correct_rank_by_time > actual_rank:
                    new_rank = correct_rank_by_time
                    logger.info(f"Promovendo {member.display_name} de Padrão {actual_rank} para Padrão {new_rank}")
                    try:
                        role_to_remove = guild.get_role(PADRAO_ROLES.get(actual_rank))
                        role_to_add = guild.get_role(PADRAO_ROLES.get(new_rank))
                        if role_to_remove: await member.remove_roles(role_to_remove, reason="Promoção Automática")
                        if role_to_add: await member.add_roles(role_to_add, reason=f"Promoção Automática para Padrão {new_rank}")
                        await db.execute("UPDATE user_promotions SET current_padrao_rank = ? WHERE user_id = ?", (new_rank, member.id))
                        await db.commit()
                        promoted_count += 1
                        if log_channel: await log_channel.send(f"📈 **PROMOÇÃO AUTOMÁTICA:** {member.mention} foi promovido para **Padrão {new_rank}** por tempo de serviço na carreira.")
                        
                        if new_rank == 6:
                            max_classe_for_carreira = CARREIRA_ROLES.get(current_carreira, {}).get('max_classe')
                            promo_record_updated = await (await db.execute("SELECT * FROM user_promotions WHERE user_id = ?", (member.id,))).fetchone()
                            if promo_record_updated['current_classe_rank'] != max_classe_for_carreira:
                                logger.info(f"Membro {member.display_name} apto para promoção de classe. Iniciando processo.")
                                await self._handle_class_promotion(member, promo_record_updated)
                            else:
                                if log_channel: await log_channel.send(f"🏆 {member.mention} atingiu o posto **Padrão 6** na classe máxima de sua carreira!")
                    except Exception as e:
                        logger.error(f"Falha ao promover {member.display_name} automaticamente: {e}")
        
        if interaction:
            await interaction.followup.send(f"✅ Verificação forçada concluída!\n- **{newly_synced_count}** membros sincronizados.\n- **{corrected_count}** cargos corrigidos.\n- **{promoted_count}** membros promovidos.", ephemeral=True)

    promocao_group = app_commands.Group(name="promocao", description="Gerencia o sistema de promoção.")

    @promocao_group.command(name="forcar_verificacao", description="Força a verificação de promoções em todos os membros.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def force_check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        logger.info(f"Verificação de promoção forçada por {interaction.user.display_name}.")
        await self.run_promotion_check(interaction)

    @promocao_group.command(name="remover", description="Remove um membro do sistema de promoção.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def remove_from_promotion(self, interaction: discord.Interaction, membro: discord.Member):
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PROMOTION) as db:
            if not await (await db.execute("SELECT 1 FROM user_promotions WHERE user_id = ?", (membro.id,))).fetchone():
                await interaction.followup.send(f"ℹ️ O membro {membro.mention} não está no sistema de promoção.", ephemeral=True)
                return
            await db.execute("DELETE FROM user_promotions WHERE user_id = ?", (membro.id,))
            await db.commit()
        roles_to_remove_ids = set(PADRAO_ROLES.values()) | set(CLASSE_ROLES.values())
        roles_to_remove = [r for r in membro.roles if r in roles_to_remove_ids]
        try:
            if roles_to_remove: await membro.remove_roles(*roles_to_remove, reason="Removido do sistema de promoção")
        except Exception as e:
            logger.error(f"Erro ao remover cargos de {membro.display_name}: {e}")
        await interaction.followup.send(f"✅ O membro {membro.mention} foi removido do sistema e seus cargos de promoção foram retirados.", ephemeral=True)

    @promocao_group.command(name="status", description="Verifica o status da promoção de um membro.")
    @app_commands.checks.has_role(ADMIN_ROLE_ID)
    async def status_promocao(self, interaction: discord.Interaction, membro: discord.Member):
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PROMOTION) as db:
            db.row_factory = aiosqlite.Row
            promo_record = await (await db.execute("SELECT * FROM user_promotions WHERE user_id = ?", (membro.id,))).fetchone()
        if not promo_record or not promo_record['current_carreira_rank']:
            await interaction.followup.send(f"ℹ️ O membro {membro.mention} não faz parte do sistema de promoção.", ephemeral=True)
            return
        current_rank = promo_record['current_padrao_rank']; current_carreira = promo_record['current_carreira_rank']

        since_date_str = promo_record['last_class_promotion_date']
        since_date = datetime.fromisoformat(since_date_str) if since_date_str else None
        total_seconds_in_carreira = await self.get_total_ponto_seconds(membro.id, since_date)

        if current_rank >= 6:
            current_classe = promo_record['current_classe_rank']
            max_classe_for_carreira = CARREIRA_ROLES.get(current_carreira, {}).get('max_classe')
            if max_classe_for_carreira and current_classe == max_classe_for_carreira:
                await interaction.followup.send(f"🏆 {membro.mention} atingiu o cargo máximo da carreira: **Padrão 6 - {current_classe} Classe**.", ephemeral=True)
            else:
                await interaction.followup.send(f"⬆️ {membro.mention} está em **Padrão 6 - {current_classe} Classe** e está apto para ser promovido para a próxima classe na próxima verificação automática.", ephemeral=True)
            return
        
        next_rank = current_rank + 1
        multiplier = CARREIRA_ROLES.get(current_carreira, {}).get('multiplier', 1.0)
        base_required_seconds = TIME_REQUIREMENTS_SECONDS.get(next_rank, 0)
        required_seconds = int(base_required_seconds * multiplier)
        embed = discord.Embed(title=f"📊 Status de Promoção - {membro.display_name}", color=discord.Color.blue())
        embed.set_thumbnail(url=membro.display_avatar.url)
        embed.add_field(name="Carreira", value=current_carreira, inline=False)
        embed.add_field(name="Cargo Atual", value=f"Padrão {current_rank}", inline=True)
        embed.add_field(name="Próximo Cargo", value=f"Padrão {next_rank}", inline=True)
        embed.add_field(name="Multiplicador", value=f"{multiplier}x", inline=True)
        embed.add_field(name=f"Tempo na Classe Atual", value=self.format_seconds(total_seconds_in_carreira), inline=True)
        embed.add_field(name="Tempo Necessário", value=self.format_seconds(required_seconds), inline=True)
        remaining_seconds = required_seconds - total_seconds_in_carreira
        embed.add_field(name="Tempo Restante", value="✅ Apto para promoção!" if remaining_seconds <= 0 else self.format_seconds(remaining_seconds), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @promocao_group.command(name="manual", description="Ajusta manualmente o cargo de um membro.")
    @is_super_admin()
    @app_commands.describe(membro="O membro a ser ajustado.", novo_padrao="O novo cargo Padrão.", nova_classe="O novo cargo de Classe.")
    @app_commands.choices(novo_padrao=[app_commands.Choice(name=f"Padrão {i}", value=i) for i in range(1, 7)], nova_classe=[app_commands.Choice(name=name, value=name) for name in CLASSE_ROLES.keys()])
    async def manual_promotion(self, interaction: discord.Interaction, membro: discord.Member, novo_padrao: int, nova_classe: str):
        await interaction.response.defer(ephemeral=True)
        carreira_role_ids = {v['role_id']: k for k, v in CARREIRA_ROLES.items()}
        member_role_ids = {r.id for r in membro.roles}
        current_carreira = next((name for role_id, name in carreira_role_ids.items() if role_id in member_role_ids), None)
        if not current_carreira:
            await interaction.followup.send("❌ O membro precisa ter um cargo de Carreira para ser ajustado no sistema.", ephemeral=True)
            return
        async with aiosqlite.connect(DB_PROMOTION) as db:
            now_iso = datetime.now().isoformat()
            await db.execute("INSERT INTO user_promotions (user_id, current_padrao_rank, current_classe_rank, current_carreira_rank, last_class_promotion_date) VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET current_padrao_rank = excluded.current_padrao_rank, current_classe_rank = excluded.current_classe_rank, current_carreira_rank = excluded.current_carreira_rank, last_class_promotion_date = excluded.last_class_promotion_date", (membro.id, novo_padrao, nova_classe, current_carreira, now_iso))
            await db.commit()
        roles_to_add_ids = {PADRAO_ROLES.get(novo_padrao), CLASSE_ROLES.get(nova_classe)}
        roles_to_remove_ids = set(PADRAO_ROLES.values()) | set(CLASSE_ROLES.values())
        roles_to_add = [interaction.guild.get_role(rid) for rid in roles_to_add_ids if rid]
        roles_to_remove = [r for r in membro.roles if r.id in roles_to_remove_ids]
        try:
            if roles_to_remove: await membro.remove_roles(*roles_to_remove, reason=f"Ajuste manual por {interaction.user.name}")
            if roles_to_add: await membro.add_roles(*roles_to_add, reason=f"Ajuste manual por {interaction.user.name}")
        except Exception as e:
            logger.error(f"Erro ao ajustar cargos manualmente para {membro.display_name}: {e}")
            await interaction.followup.send("❌ Ocorreu um erro ao tentar alterar os cargos do membro.", ephemeral=True)
            return
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🛠️ **AJUSTE MANUAL:** {interaction.user.mention} ajustou o cargo de {membro.mention} para **Padrão {novo_padrao}** e **{nova_classe} Classe**. A contagem de horas foi reiniciada.")
        await interaction.followup.send(f"✅ O cargo de {membro.mention} foi ajustado com sucesso.", ephemeral=True)

    # <--- NOVO COMANDO ADICIONADO AQUI
    @promocao_group.command(name="resetar_horas", description="Reseta a contagem de horas de um membro para o ciclo de promoção atual.")
    @is_super_admin()
    async def reset_hours(self, interaction: discord.Interaction, membro: discord.Member):
        """Reseta o marco inicial da contagem de horas de um membro."""
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PROMOTION) as db:
            # Verifica se o membro realmente existe no sistema de promoção
            cursor = await db.execute("SELECT 1 FROM user_promotions WHERE user_id = ?", (membro.id,))
            if await cursor.fetchone() is None:
                await interaction.followup.send(f"❌ O membro {membro.mention} não está no sistema de promoção e, portanto, não pode ter suas horas resetadas.", ephemeral=True)
                return

            # Atualiza a data da última promoção para "agora", resetando a contagem
            now_iso = datetime.now().isoformat()
            await db.execute(
                "UPDATE user_promotions SET last_class_promotion_date = ? WHERE user_id = ?",
                (now_iso, membro.id)
            )
            await db.commit()
            logger.info(f"Horas de {membro.display_name} resetadas manualmente por {interaction.user.display_name}.")

        # Envia um log da ação administrativa
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"⏳ **RESET DE HORAS MANUAL:** {interaction.user.mention} resetou a contagem de horas de carreira de {membro.mention}.")

        # Confirma a execução para o super admin
        await interaction.followup.send(f"✅ A contagem de horas de {membro.mention} foi resetada com sucesso. A nova contagem começará a partir de agora.", ephemeral=True)
    # <--- FIM DO NOVO COMANDO

    @tasks.loop(minutes=10.0)
    async def promotion_check_task(self):
        await self.bot.wait_until_ready()
        logger.info("Executando tarefa de verificação de promoções...")
        await self.run_promotion_check()
        logger.info("Tarefa de verificação de promoções concluída.")

async def setup(bot: commands.Bot):
    if not all([GUILD_ID, ADMIN_ROLE_ID, SUPER_ADMIN_ID, LOG_CHANNEL_ID]):
        logger.error("Não foi possível carregar 'PromocaoCog' devido a configs ausentes.")
        return
    cog = PromocaoCog(bot)
    bot.tree.add_command(cog.promocao_group, guild=discord.Object(id=GUILD_ID))
    await bot.add_cog(cog)