# init.py
import discord
from discord.ext import commands
import json
import logging
import asyncio
import os

# --- 1. CONFIGURAÇÃO E LOGGING ---
logger = logging.getLogger('discord_bot')
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(filename='bot.log', encoding='utf-8', mode='w')
formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
file_handler.setFormatter(formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

try:
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    TOKEN = config.get('TOKEN')
    GUILD_ID = config.get('GUILD_ID')
except FileNotFoundError:
    logger.critical("ERRO CRÍTICO: O arquivo 'config.json' não foi encontrado.")
    exit()

# --- 2. DEFINIÇÃO DO BOT ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- 3. LÓGICA DE CARREGAMENTO DOS COGS ---
async def load_all_cogs():
    cogs_path = './cogs'
    logger.info("Procurando por cogs para carregar...")
    if not os.path.exists(cogs_path):
        os.makedirs(cogs_path)

    for filename in os.listdir(cogs_path):
        # Carrega apenas arquivos que terminam com "_cog.py"
        if filename.endswith('_cog.py'):
            cog_name = f'cogs.{filename[:-3]}'
            try:
                await bot.load_extension(cog_name)
                logger.info(f"Cog '{cog_name}' carregado com sucesso.")
            except Exception as e:
                logger.error(f"Falha ao carregar o cog '{cog_name}'.", exc_info=e)

# --- 4. EVENTOS DO BOT ---
@bot.event
async def on_ready():
    logger.info(f'Bot conectado como {bot.user.name}')

@bot.event
async def setup_hook():
    await load_all_cogs()
    if GUILD_ID:
        guild_obj = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild_obj)
        logger.info(f"{len(synced)} comandos de barra sincronizados.")

# --- 5. INICIALIZAÇÃO ---
async def main():
    if not TOKEN:
        logger.critical("ERRO CRÍTICO: O token não foi definido no config.json.")
        return
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())