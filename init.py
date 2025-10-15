# init.py
import discord
from discord.ext import commands
from discord import app_commands
import json
import logging
import asyncio
import os

# --- 1. CONFIGURAÇÃO E LOGGING ---
logger = logging.getLogger('discord_bot')
logger.setLevel(logging.INFO)

# Evita adicionar handlers duplicados se o script for recarregado
if not logger.handlers:
    file_handler = logging.FileHandler(filename='bot.log', encoding='utf-8', mode='w')
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# Carrega as configurações essenciais para o bot iniciar do config.json
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    TOKEN = config.get('TOKEN')
    GUILD_ID = config.get('GUILD_ID')
    OWNER_ID = config.get('OWNER_ID')
except FileNotFoundError:
    logger.critical("ERRO CRÍTICO: O arquivo 'config.json' não foi encontrado.")
    exit()
except json.JSONDecodeError:
    logger.critical("ERRO CRÍTICO: O arquivo 'config.json' está mal formatado.")
    exit()

# --- 2. DEFINIÇÃO DO BOT ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, owner_id=OWNER_ID)

# --- 3. LÓGICA DE CARREGAMENTO DOS COGS ---
async def load_all_cogs():
    """Encontra e carrega todos os módulos na pasta /cogs."""
    cogs_path = './cogs'
    logger.info("Procurando por cogs para carregar...")
    if not os.path.exists(cogs_path):
        os.makedirs(cogs_path)

    for filename in os.listdir(cogs_path):
        # Carrega qualquer arquivo Python que não comece com __ (arquivos de suporte)
        if filename.endswith('.py') and not filename.startswith('__'):
            cog_name = f'cogs.{filename[:-3]}'
            try:
                await bot.load_extension(cog_name)
                logger.info(f"Cog '{cog_name}' carregado com sucesso.")
            except commands.NoEntryPointError:
                logger.warning(f"Arquivo '{cog_name}' ignorado pois não possui uma função 'setup'.")
            except Exception as e:
                logger.error(f"Falha ao carregar o cog '{cog_name}'.", exc_info=e)

# --- 4. COMANDO DE GERENCIAMENTO DE COGS ---
@bot.tree.command(name="cog", description="Gerencia os módulos (cogs) do bot.")
@app_commands.describe(action="A ação a ser executada", module="O nome do arquivo do módulo (ex: units_cog)")
@app_commands.choices(action=[
    discord.app_commands.Choice(name="Recarregar (Reload)", value="reload"),
    discord.app_commands.Choice(name="Carregar (Load)", value="load"),
    discord.app_commands.Choice(name="Descarregar (Unload)", value="unload"),
])
async def cog_management(interaction: discord.Interaction, action: str, module: str):
    if interaction.user.id != bot.owner_id:
        await interaction.response.send_message("❌ Apenas o dono do bot pode usar este comando.", ephemeral=True)
        return
    
    cog_name = f"cogs.{module}"
    try:
        if action == "reload":
            await bot.reload_extension(cog_name)
            msg = f"✅ Módulo `{module}` recarregado com sucesso!"
        elif action == "load":
            await bot.load_extension(cog_name)
            msg = f"✅ Módulo `{module}` carregado com sucesso!"
        elif action == "unload":
            await bot.unload_extension(cog_name)
            msg = f"✅ Módulo `{module}` descarregado com sucesso!"
        
        logger.info(f"Ação '{action}' executada no módulo '{module}' por {interaction.user}.")
        await interaction.response.send_message(msg, ephemeral=True)
        
    except commands.ExtensionError as e:
        logger.error(f"Erro ao gerenciar o cog '{cog_name}':", exc_info=e)
        await interaction.response.send_message(f"❌ Erro ao executar a ação `{action}` no módulo `{module}`.\n`{e}`", ephemeral=True)

@cog_management.autocomplete('module')
async def cog_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cogs = [f[:-3] for f in os.listdir('./cogs') if f.endswith('.py') and not f.startswith('__')]
    return [
        app_commands.Choice(name=cog, value=cog)
        for cog in cogs if current.lower() in cog.lower()
    ]

# --- 5. EVENTOS DO BOT ---
@bot.event
async def on_ready():
    logger.info(f'Bot conectado como {bot.user.name}')
    print("-" * 30); print(f'Bot {bot.user.name} está online!'); print("-" * 30)

@bot.event
async def setup_hook():
    await load_all_cogs()
    if GUILD_ID:
        guild_obj = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild_obj)
        logger.info(f"{len(synced)} comandos de barra sincronizados com o servidor {GUILD_ID}.")

# --- 6. INICIALIZAÇÃO ---
async def main():
    if not TOKEN:
        logger.critical("ERRO CRÍTICO: O token não está definido no config.json.")
        return
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())