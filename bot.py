import os
import zipfile
import subprocess
import discord
from discord.ext import commands

# --- DESCOMPRESIÓN AUTOMÁTICA ---
ZIP_FILE = "luraphv15_1_deobf.zip"
TARGET_DIR = "v15_tool_attempt_source"

if os.path.exists(ZIP_FILE) and not os.path.exists(TARGET_DIR):
    print(f"📦 Descomprimiendo {ZIP_FILE}...")
    with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
        zip_ref.extractall(TARGET_DIR)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

@bot.event
async def on_ready():
    print(f"¡El bot está en línea y conectado como: {bot.user}!")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="scripts | .luraph"))

@bot.command(name="luraph", help="Desofusca scripts de Luraph adjuntando un archivo .lua o .txt")
async def deobfuscate_luraph(ctx):
    if not ctx.message.attachments:
        await ctx.send("# :incorrect: Error\nEl código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.")
        return

    attachment = ctx.message.attachments[0]
    
    if not attachment.filename.lower().endswith((".txt", ".lua")):
        await ctx.send("# :incorrect: Error\nEl código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.")
        return

    if attachment.size > 5 * 1024 * 1024:
        await ctx.send("# :incorrect: Error\nEl código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.")
        return

    # Mensaje de carga inicial
    status_message = await ctx.send("# :loading: Deobfuscando\nEstamos Deobfuscando tu código, se paciente.")

    input_filename = f"input_{ctx.author.id}.lua"
    output_filename = f"output_{ctx.author.id}.lua"

    try:
        # 1. Guardar archivo adjunto
        await attachment.save(input_filename)

        # 2. Ejecutar la herramienta Node.js con un límite de tiempo de 30 segundos
        cmd = ["node", "v15_tool_attempt_source/v15_tool_attempt_source/deob.js", input_filename, output_filename]
        
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Verificar si hubo error o no se creó el archivo de salida
        if process.returncode != 0 or not os.path.exists(output_filename):
            error_details = process.stderr.strip() or process.stdout.strip() or "Error desconocido en el script de Node.js."
            
            # Enviar mensaje público de error
            await status_message.edit(content="# :incorrect: Error\nEl código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.")
            
            # Enviar detalles por MD al usuario
            try:
                await ctx.author.send(f"⚠️ **Detalle del fallo de desofuscación:**\n```{error_details[:1900]}```")
            except discord.Forbidden:
                pass # Si el usuario tiene los MD cerrados
            return

        # 3. Leer el resultado generado con éxito
        with open(output_filename, "r", encoding="utf-8", errors="ignore") as f:
            deobfuscated_code = f.read()

        # Agregar la firma personalizada al inicio
        final_content = f"-- Deobfuscado por Lexy Hub\n\n{deobfuscated_code}"

        final_filename = "deobfuscated_lexyhub.lua"
        with open(final_filename, "w", encoding="utf-8") as f:
            f.write(final_content)

        # Editar mensaje con éxito y enviar archivo
        await status_message.edit(content="# :correct: Deobfuscado\nTu código fue Deobfuscado correctamente.")
        await ctx.send(file=discord.File(final_filename, filename="deobfuscated_lexyhub.lua"))

    except subprocess.TimeoutExpired:
        await status_message.edit(content="# :incorrect: Error\nEl código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.")
        try:
            await ctx.author.send("⚠️ **Detalle del fallo:** El proceso tardó demasiado tiempo (Timeout de 30 segundos) y fue cancelado.")
        except discord.Forbidden:
            pass
        
    except Exception as e:
        await status_message.edit(content="# :incorrect: Error\nEl código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.")
        try:
            await ctx.author.send(f"⚠️ **Detalle del error inesperado:**\n```{str(e)}```")
        except discord.Forbidden:
            pass
    
    finally:
        # Limpieza de archivos temporales
        for temp_file in [input_filename, output_filename, "deobfuscated_lexyhub.lua"]:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
