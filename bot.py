import os
import zipfile
import discord
from discord.ext import commands

# --- DIAGNÓSTICO PROFUNDO DE ARCHIVOS ---
ZIP_FILE = "luraphv15_1_deobf.zip"
TARGET_DIR = "v15_tool_attempt_source"

if os.path.exists(ZIP_FILE) and not os.path.exists(TARGET_DIR):
    print(f"📦 Descomprimiendo {ZIP_FILE}...")
    with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
        zip_ref.extractall(TARGET_DIR)

# Recorrer y listar TODOS los archivos de la carpeta para ver cuál es el desofuscador real
print("📂 LISTA DE TODOS LOS ARCHIVOS DESCOMPRIMIDOS:")
for root, dirs, files in os.walk(TARGET_DIR):
    for file in files:
        print(os.path.join(root, file))

# Configuración de intenciones (Intents)
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

@bot.event
async def on_ready():
    print(f"¡El bot está en línea y conectado como: {bot.user}!")

@bot.command(name="luraph")
async def deobfuscate_luraph(ctx):
    await ctx.send("🔍 Analizando herramienta... Revisa los logs de Railway para ver el nombre correcto del script de desofuscación.")

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
