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
        embed_error = discord.Embed(
            title="⚠️ Archivo faltante",
            description="Por favor, adjunta un archivo `.txt` o `.lua` junto al comando.\n\n**Ejemplo:** `.luraph` (con el archivo adjunto)",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed_error)
        return

    attachment = ctx.message.attachments[0]
    
    if not attachment.filename.lower().endswith((".txt", ".lua")):
        embed_ext = discord.Embed(
            title="❌ Formato incorrecto",
            description="El archivo adjunto debe ser estrictamente un formato de texto (`.txt` o `.lua`).",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed_ext)
        return

    if attachment.size > 5 * 1024 * 1024:
        await ctx.send("❌ El archivo es demasiado grande. El límite permitido es de 5 MB.")
        return

    embed_loading = discord.Embed(
        title="⏳ Procesando script...",
        description="Ejecutando el motor de desofuscación Node.js. Por favor espera un momento.",
        color=discord.Color.blue()
    )
    status_message = await ctx.send(embed=embed_loading)

    input_filename = f"input_{ctx.author.id}.lua"
    output_filename = f"output_{ctx.author.id}.lua"

    try:
        # 1. Guardar el archivo adjunto
        await attachment.save(input_filename)

        # 2. Ejecutar la herramienta real (deob.js con Node.js)
        cmd = ["node", "v15_tool_attempt_source/v15_tool_attempt_source/deob.js", input_filename, output_filename]
        
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=45)

        if process.returncode != 0:
            error_msg = process.stderr.strip() or process.stdout.strip() or "Error desconocido en el script de Node.js."
            embed_fail = discord.Embed(
                title="⚠️ Fallo en la desofuscación",
                description=f"No se ha podido procesar el script.\n\n**Detalle técnico:**\n```{error_msg[:1000]}```",
                color=discord.Color.red()
            )
            await status_message.edit(embed=embed_fail)
            return

        # 3. Leer el resultado generado
        if os.path.exists(output_filename):
            with open(output_filename, "r", encoding="utf-8", errors="ignore") as f:
                deobfuscated_code = f.read()
        else:
            deobfuscated_code = process.stdout

        # Agregar la firma personalizada en la parte superior
        final_content = f"-- Deobfuscado por Lexy Hub\n\n{deobfuscated_code}"

        final_filename = "deobfuscated_lexyhub.lua"
        with open(final_filename, "w", encoding="utf-8") as f:
            f.write(final_content)

        # 4. Enviar archivo limpio
        embed_success = discord.Embed(
            title="✅ ¡Desofuscación Exitosa!",
            description=f"Script procesado correctamente para **{ctx.author.display_name}**.",
            color=discord.Color.green()
        )
        embed_success.set_footer(text="Lexy Hub Protection & Tools")

        await status_message.edit(embed=embed_success)
        await ctx.send(file=discord.File(final_filename, filename="deobfuscated_lexyhub.lua"))

    except subprocess.TimeoutExpired:
        embed_timeout = discord.Embed(
            title="⏱️ Tiempo agotado",
            description="El proceso de desofuscación tardó demasiado tiempo y fue cancelado automáticamente.",
            color=discord.Color.orange()
        )
        await status_message.edit(embed=embed_timeout)
        
    except Exception as e:
        embed_err = discord.Embed(
            title="❌ Error Inesperado",
            description=f"Ocurrió un fallo en el servidor:\n```{str(e)}```",
            color=discord.Color.red()
        )
        await status_message.edit(embed=embed_err)
    
    finally:
        for temp_file in [input_filename, output_filename, "deobfuscated_lexyhub.lua"]:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
