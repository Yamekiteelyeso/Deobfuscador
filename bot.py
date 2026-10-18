import os
import zipfile
import subprocess
import shutil
import json
import aiohttp
import discord
from discord.ext import commands

# --- EMOJIS PERSONALIZADOS ---
EMOJI_LOADING = "⏳"
EMOJI_CORRECT = "<:correct:1561435171385909288>"
EMOJI_INCORRECT = "<:incorrect:1561436020766146590>"

# --- DESCOMPRESIÓN AUTOMÁTICA DE LA HERRAMIENTA ---
ZIP_FILE = "luraphv15_1_deobf.zip"
TARGET_DIR = "v15_tool_attempt_source"

if os.path.exists(ZIP_FILE) and not os.path.exists(TARGET_DIR):
    print(f"📦 Descomprimiendo {ZIP_FILE}...")
    with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
        zip_ref.extractall(TARGET_DIR)

# Configuración de intenciones (Intents)
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"¡El bot está en línea y conectado como: {bot.user}!")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="scripts | .help"))

# ==================== COMANDO: .HELP ====================
@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="🤖 Panel de Ayuda - Lexy Hub",
        description="Bienvenido al centro de herramientas. Aquí tienes la lista de comandos disponibles:",
        color=discord.Color.dark_purple()
    )
    
    embed.add_field(
        name="🔓 `.luraph`",
        value="Desofusca un script de Luraph. Puedes **adjuntar un archivo** (`.lua`/`.txt`) o pasar una **URL** (Pastefy, Pastebin, Raw).\n**Ejemplo:** `.luraph https://pastefy.app/jwjdsj/raw`",
        inline=False
    )
    embed.add_field(
        name="📥 `.get <url>`",
        value="Obtiene y muestra el contenido de texto de una URL directamente.\n**Ejemplo:** `.get https://pastefy.app/jwjdsj/raw`",
        inline=False
    )
    embed.add_field(
        name="ℹ️ `.help`",
        value="Muestra este panel de ayuda.",
        inline=False
    )
    
    embed.set_footer(text="Lexy Hub Protection & Tools")
    await ctx.send(embed=embed)

# ==================== COMANDO: .GET ====================
@bot.command(name="get")
async def cmd_get(ctx, url: str = None):
    if not url:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="Debes proporcionar una URL válida.\n\n**Ejemplo:** `.get https://pastefy.app/jwjdsj/raw`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed_err)
        return

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    embed_loading = discord.Embed(
        title=f"{EMOJI_LOADING} Descargando contenido...",
        description=f"Obteniendo datos de la URL proporcionada...",
        color=discord.Color.blue()
    )
    status_msg = await ctx.send(embed=embed_loading)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    embed_err = discord.Embed(
                        title=f"{EMOJI_INCORRECT} Error",
                        description=f"No se pudo obtener el contenido. Código HTTP: `{response.status}`",
                        color=discord.Color.red()
                    )
                    await status_msg.edit(embed=embed_err)
                    return

                content = await response.text()

        if not content.strip():
            embed_empty = discord.Embed(
                title=f"{EMOJI_INCORRECT} Error",
                description="La URL proporcionada no contiene texto o está vacía.",
                color=discord.Color.red()
            )
            await status_msg.edit(embed=embed_empty)
            return

        if len(content) <= 1900:
            await status_msg.delete()
            await ctx.send(f"```lua\n{content}\n```")
        else:
            temp_file = f"get_{ctx.author.id}.lua"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(content)

            embed_success = discord.Embed(
                title=f"{EMOJI_CORRECT} Contenido descargado",
                description="El contenido supera el límite de texto y se adjuntó como archivo.",
                color=discord.Color.green()
            )
            await status_msg.edit(embed=embed_success)
            await ctx.send(file=discord.File(temp_file, filename="script_descargado.lua"))

            if os.path.exists(temp_file):
                os.remove(temp_file)

    except Exception as e:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="Ocurrió un error al intentar acceder a la URL. Verifica que el enlace sea correcto y público.",
            color=discord.Color.red()
        )
        await status_msg.edit(embed=embed_err)

# ==================== COMANDO: .LURAPH (Archivos o Enlaces) ====================
@bot.command(name="luraph")
async def deobfuscate_luraph(ctx, url: str = None):
    input_filename = f"input_{ctx.author.id}.lua"
    output_filename = f"output_{ctx.author.id}.lua"

    has_attachment = bool(ctx.message.attachments)
    
    if not has_attachment and not url:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="El código no se pudo deobfuscar, por favor adjunta un archivo `.lua`/`.txt` o proporciona una URL válida de Pastefy/Pastebin.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed_err)
        return

    embed_loading = discord.Embed(
        title=f"{EMOJI_LOADING} Deobfuscando",
        description="Estamos Deobfuscando tu código, sé paciente.",
        color=discord.Color.blue()
    )
    status_message = await ctx.send(embed=embed_loading)

    try:
        # CASO A: Archivo adjunto
        if has_attachment:
            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith((".txt", ".lua")):
                await status_message.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="El archivo debe ser formato `.txt` o `.lua`.", color=discord.Color.red()))
                return
            if attachment.size > 5 * 1024 * 1024:
                await status_message.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="El archivo es demasiado grande (Máx 5MB).", color=discord.Color.red()))
                return
            await attachment.save(input_filename)

        # CASO B: URL proporcionada
        elif url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status != 200:
                        await status_message.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="No se pudo descargar el contenido de la URL proporcionada.", color=discord.Color.red()))
                        return
                    script_content = await response.text()
            
            if not script_content.strip():
                await status_message.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="La URL está vacía o no contiene texto válido.", color=discord.Color.red()))
                return

            with open(input_filename, "w", encoding="utf-8") as f:
                f.write(script_content)

        # 2. Encontrar Node.js dinámicamente y ejecutar la herramienta
        node_bin = shutil.which("node") or shutil.which("nodejs") or "node"
        cmd = [node_bin, "v15_tool_attempt_source/v15_tool_attempt_source/deob.js", input_filename, output_filename]
        
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        deobfuscated_code = ""
        output_file_from_json = None

        raw_stdout = process.stdout.strip()
        try:
            json_start = raw_stdout.find('{')
            json_end = raw_stdout.rfind('}')
            if json_start != -1 and json_end != -1:
                json_data = json.loads(raw_stdout[json_start:json_end+1])
                if json_data.get("success") and "output" in json_data:
                    output_file_from_json = json_data["output"]
        except Exception:
            pass

        if output_file_from_json and os.path.exists(output_file_from_json):
            with open(output_file_from_json, "r", encoding="utf-8", errors="ignore") as f:
                deobfuscated_code = f.read()
        elif os.path.exists(output_filename):
            with open(output_filename, "r", encoding="utf-8", errors="ignore") as f:
                deobfuscated_code = f.read()

        if not deobfuscated_code.strip():
            error_details = process.stderr.strip() or raw_stdout or "Error desconocido al procesar el JSON de salida."
            
            embed_err = discord.Embed(
                title=f"{EMOJI_INCORRECT} Error",
                description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
                color=discord.Color.red()
            )
            await status_message.edit(embed=embed_err)
            
            try:
                await ctx.author.send(f"⚠️ **Detalle del fallo de desofuscación:**\n```{error_details[:1900]}```")
            except discord.Forbidden:
                pass
            return

        # 3. Formatear contenido final
        final_content = f"-- Deobfuscado por Lexy Hub\n\n{deobfuscated_code}"
        
        # Guardar en archivo para adjuntar SIEMPRE
        final_filename = "deobfuscated_lexyhub.lua"
        with open(final_filename, "w", encoding="utf-8") as f:
            f.write(final_content)

        # Crear una vista previa muy pequeña (primeros 300 caracteres)
        preview_code = final_content[:300].strip()
        if len(final_content) > 300:
            preview_code += "\n..."

        embed_success = discord.Embed(
            title=f"{EMOJI_CORRECT} SUCCESSFULLY FETCHED",
            description=f"**Fetched:**\n```lua\n{preview_code}\n```",
            color=discord.Color.green()
        )
        embed_success.set_footer(text="Lexy Hub Protection & Tools")

        # Editar mensaje y enviar SIEMPRE el archivo adjunto
        await status_message.edit(embed=embed_success)
        await ctx.send(file=discord.File(final_filename, filename="deobfuscated_lexyhub.lua"))

        # Limpiar archivo generado tras enviarlo
        if os.path.exists(final_filename):
            os.remove(final_filename)

        if output_file_from_json and os.path.exists(output_file_from_json):
            try:
                os.remove(output_file_from_json)
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
            color=discord.Color.red()
        )
        await status_message.edit(embed=embed_err)
        try:
            await ctx.author.send("⚠️ **Detalle del fallo:** El proceso tardó demasiado tiempo y fue cancelado.")
        except discord.Forbidden:
            pass
        
    except Exception as e:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
            color=discord.Color.red()
        )
        await status_message.edit(embed=embed_err)
        try:
            await ctx.author.send(f"⚠️ **Detalle del error inesperado:**\n```{str(e)}```")
        except discord.Forbidden:
            pass
    
    finally:
        for temp_file in [input_filename, output_filename]:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ Error crítico: La variable de entorno DISCORD_TOKEN no está configurada.")
else:
    bot.run(TOKEN)
