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

# ==================== FUNCIÓN AUXILIAR: FORMATEAR LUA (BEAUTIFY) ====================
def beautify_lua_code(code: str) -> str:
    """Función para ordenar la indentación de código Lua de forma básica y limpia."""
    lines = code.splitlines()
    formatted_lines = []
    indent_level = 0
    indent_str = "    " # 4 espacios

    # Palabras clave que aumentan o disminuyen la indentación
    increase_keywords = {"do", "then", "repeat", "function"}
    block_starters = {"if", "for", "while", "local function"}

    for line in lines:
        stripped = line.strip()
        
        # Reducir indentación en cierres o palabras de salida
        if stripped.startswith(("end", "until", "else", "elseif")) or stripped == "}":
            indent_level = max(0, indent_level - 1)

        formatted_lines.append((indent_str * indent_level) + stripped)

        # Aumentar indentación si la línea abre un bloque
        lower_line = stripped.lower()
        if any(lower_line.startswith(kw) for kw in block_starters) and (any(kw in lower_line for kw in increase_keywords) or lower_line.endswith("do") or lower_line.endswith("then")):
            indent_level += 1
        elif stripped in {"do", "repeat"} or stripped.endswith("{"):
            indent_level += 1
        elif lower_line.startswith("else") or lower_line.startswith("elseif"):
            indent_level += 1

    return "\n".join(formatted_lines)

# ==================== COMANDO: .HELP ====================
@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="✨ Centro de Herramientas - Lexy Hub",
        description=(
            "Bienvenido al panel oficial de comandos. Aquí puedes desofuscar scripts "
            "de Luraph v15, embellecer código o descargar recursos de forma segura."
        ),
        color=discord.Color.from_rgb(138, 43, 226)
    )
    
    embed.add_field(
        name="🔓 `.luraph <URL opcional>`",
        value=(
            "Desofusca un script protegido con Luraph v15.\n"
            "• Adjunta un archivo `.lua`/`.txt` o usa una URL (Pastefy, Raw).\n"
            "**Ejemplo:** `.luraph https://pastefy.app/jwjdsj/raw`"
        ),
        inline=False
    )

    embed.add_field(
        name="✨ `.beautify <URL opcional>`",
        value=(
            "Ordena, formatea y limpia la indentación de un script Lua/Luau.\n"
            "• Adjunta un archivo o proporciona una URL directa.\n"
            "**Ejemplo:** `.beautify https://pastefy.app/jwjdsj/raw`"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📥 `.get <URL>`",
        value=(
            "Descarga y muestra el contenido de texto plano de cualquier URL pública.\n"
            "**Ejemplo:** `.get https://pastefy.app/jwjdsj/raw`"
        ),
        inline=False
    )
    
    embed.add_field(
        name="ℹ️ `.help`",
        value="Muestra este panel detallado con la lista completa de comandos.",
        inline=False
    )
    
    embed.set_footer(
        text="Lexy Hub Protection & Tools • Desarrollado para alta velocidad",
        icon_url=bot.user.display_avatar.url if bot.user.display_avatar else None
    )
    await ctx.send(embed=embed)

# ==================== COMANDO: .GET ====================
@bot.command(name="get")
async def cmd_get(ctx, url: str = None):
    if not url:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Parámetro Faltante",
            description=(
                "Debes proporcionar una URL válida para descargar su contenido.\n\n"
                "**Uso correcto:** `.get <URL>`\n"
                "**Ejemplo:** `.get https://pastefy.app/jwjdsj/raw`"
            ),
            color=discord.Color.from_rgb(235, 59, 90)
        )
        await ctx.send(embed=embed_err)
        return

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    embed_loading = discord.Embed(
        title=f"{EMOJI_LOADING} Procesando Solicitud",
        description="Conectando con el servidor remoto y extrayendo contenido...",
        color=discord.Color.from_rgb(45, 152, 218)
    )
    status_msg = await ctx.send(embed=embed_loading)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    embed_err = discord.Embed(
                        title=f"{EMOJI_INCORRECT} Error de Conexión",
                        description=f"El servidor respondió con un código de estado no válido: `{response.status}`.",
                        color=discord.Color.from_rgb(235, 59, 90)
                    )
                    await status_msg.edit(embed=embed_err)
                    return

                content = await response.text()

        if not content.strip():
            embed_empty = discord.Embed(
                title=f"{EMOJI_INCORRECT} Documento Vacío",
                description="La URL proporcionada se abrió correctamente, pero no contiene texto ni código.",
                color=discord.Color.from_rgb(235, 59, 90)
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
                title=f"{EMOJI_CORRECT} Contenido Descargado Exitosamente",
                description="El texto es demasiado extenso para enviarlo por mensaje, por lo que se ha adjuntado como un archivo descargable.",
                color=discord.Color.from_rgb(32, 191, 107)
            )
            embed_success.set_footer(text="Lexy Hub Protection & Tools")
            await status_msg.edit(embed=embed_success)
            await ctx.send(file=discord.File(temp_file, filename="script_descargado.lua"))

            if os.path.exists(temp_file):
                os.remove(temp_file)

    except Exception as e:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error al Descargar",
            description="Ocurrió un fallo al intentar acceder a la URL. Verifica que el enlace sea público y válido.",
            color=discord.Color.from_rgb(235, 59, 90)
        )
        await status_msg.edit(embed=embed_err)

# ==================== COMANDO: .BEAUTIFY (Archivos o Enlaces) ====================
@bot.command(name="beautify")
async def beautify_script(ctx, url: str = None):
    has_attachment = bool(ctx.message.attachments)
    
    if not has_attachment and not url:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="Por favor adjunta un archivo `.lua`/`.txt` o proporciona una URL válida para embellecer.",
            color=discord.Color.from_rgb(235, 59, 90)
        )
        await ctx.send(embed=embed_err)
        return

    embed_loading = discord.Embed(
        title=f"{EMOJI_LOADING} Embelleciendo código",
        description="Ordenando la indentación y dando formato al script...",
        color=discord.Color.from_rgb(52, 152, 219)
    )
    status_message = await ctx.send(embed=embed_loading)

    try:
        source_identifier = "Archivo adjunto"
        raw_code = ""

        if has_attachment:
            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith((".txt", ".lua")):
                await status_message.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="El archivo debe ser formato `.txt` or `.lua`.", color=discord.Color.from_rgb(235, 59, 90)))
                return
            source_identifier = attachment.filename
            raw_code = (await attachment.read()).decode("utf-8", errors="ignore")
        elif url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            source_identifier = url
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status != 200:
                        await status_message.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="No se pudo descargar el contenido de la URL.", color=discord.Color.from_rgb(235, 59, 90)))
                        return
                    raw_code = await response.text()

        if not raw_code.strip():
            await status_message.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="El contenido está vacío.", color=discord.Color.from_rgb(235, 59, 90)))
            return

        # Aplicar formato beautify
        beautified_code = beautify_lua_code(raw_code)
        final_content = f"-- Formateado por Lexy Hub\n\n{beautified_code}"

        final_filename = "beautified_lexyhub.lua"
        with open(final_filename, "w", encoding="utf-8") as f:
            f.write(final_content)

        preview_code = final_content[:400].strip()
        if len(final_content) > 400:
            preview_code += "\n..."

        embed_success = discord.Embed(
            title=f"{EMOJI_CORRECT} SUCCESSFULLY BEAUTIFIED",
            description=f"🔗 **Fuente:** `{source_identifier}`\n\n**Fetched:**\n```lua\n{preview_code}\n```",
            color=discord.Color.from_rgb(32, 191, 107)
        )
        embed_success.set_footer(text="Lexy Hub Protection & Tools")

        await status_message.edit(embed=embed_success)
        await ctx.send(file=discord.File(final_filename, filename="beautified_lexyhub.lua"))

        if os.path.exists(final_filename):
            os.remove(final_filename)

    except Exception as e:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description=f"Ocurrió un error inesperado al procesar el código: ```{str(e)[:200]}```",
            color=discord.Color.from_rgb(235, 59, 90)
        )
        await status_message.edit(embed=embed_err)

# ==================== COMANDO: .LURAPH (Archivos o Enlaces) ====================
@bot.command(name="luraph")
async def deobfuscate_luraph(ctx, url: str = None):
    input_filename = f"input_{ctx.author.id}.lua"
    output_filename = f"output_{ctx.author.id}.lua"
    specific_output_dir = "output"

    has_attachment = bool(ctx.message.attachments)
    
    if not has_attachment and not url:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
            color=discord.Color.from_rgb(235, 59, 90)
        )
        await ctx.send(embed=embed_err)
        return

    embed_loading = discord.Embed(
        title=f"{EMOJI_LOADING} Deobfuscando",
        description="Estamos Deobfuscando tu código, se paciente.",
        color=discord.Color.from_rgb(52, 152, 219)
    )
    status_message = await ctx.send(embed=embed_loading)

    try:
        source_identifier = "Archivo adjunto"
        if has_attachment:
            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith((".txt", ".lua")):
                embed_err = discord.Embed(
                    title=f"{EMOJI_INCORRECT} Error",
                    description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
                    color=discord.Color.from_rgb(235, 59, 90)
                )
                await status_message.edit(embed=embed_err)
                return
            if attachment.size > 5 * 1024 * 1024:
                embed_err = discord.Embed(
                    title=f"{EMOJI_INCORRECT} Error",
                    description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
                    color=discord.Color.from_rgb(235, 59, 90)
                )
                await status_message.edit(embed=embed_err)
                return
            await attachment.save(input_filename)
            source_identifier = attachment.filename

        elif url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            source_identifier = url
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status != 200:
                        embed_err = discord.Embed(
                            title=f"{EMOJI_INCORRECT} Error",
                            description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
                            color=discord.Color.from_rgb(235, 59, 90)
                        )
                        await status_message.edit(embed=embed_err)
                        return
                    script_content = await response.text()
            
            if not script_content.strip():
                embed_err = discord.Embed(
                    title=f"{EMOJI_INCORRECT} Error",
                    description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
                    color=discord.Color.from_rgb(235, 59, 90)
                )
                await status_message.edit(embed=embed_err)
                return

            with open(input_filename, "w", encoding="utf-8") as f:
                f.write(script_content)

        node_bin = shutil.which("node") or shutil.which("nodejs") or "node"
        cmd = [node_bin, "v15_tool_attempt_source/v15_tool_attempt_source/deob.js", input_filename, output_filename]
        
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        deobfuscated_code = ""
        output_file_from_json = None
        expected_output_path = os.path.join(specific_output_dir, input_filename)

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
        elif os.path.exists(expected_output_path):
            with open(expected_output_path, "r", encoding="utf-8", errors="ignore") as f:
                deobfuscated_code = f.read()
        elif os.path.exists(output_filename):
            with open(output_filename, "r", encoding="utf-8", errors="ignore") as f:
                deobfuscated_code = f.read()

        if not deobfuscated_code.strip():
            error_details = process.stderr.strip() or raw_stdout or "Error desconocido al procesar el JSON de salida."
            
            embed_err = discord.Embed(
                title=f"{EMOJI_INCORRECT} Error",
                description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
                color=discord.Color.from_rgb(235, 59, 90)
            )
            await status_message.edit(embed=embed_err)
            
            try:
                await ctx.author.send(f"⚠️ **Detalle del fallo de desofuscación:**\n```{error_details[:1900]}```")
            except discord.Forbidden:
                pass
            return

        final_content = f"-- Deobfuscado por Lexy Hub\n\n{deobfuscated_code}"
        
        final_filename = "deobfuscated_lexyhub.lua"
        with open(final_filename, "w", encoding="utf-8") as f:
            f.write(final_content)

        preview_code = final_content[:400].strip()
        if len(final_content) > 400:
            preview_code += "\n..."

        embed_success = discord.Embed(
            title=f"{EMOJI_CORRECT} SUCCESSFULLY FETCHED",
            description=f"🔗 **Fuente:** `{source_identifier}`\n\n**Fetched:**\n```lua\n{preview_code}\n```",
            color=discord.Color.from_rgb(32, 191, 107)
        )
        embed_success.set_footer(text="Lexy Hub Protection & Tools")

        await status_message.edit(embed=embed_success)
        await ctx.send(file=discord.File(final_filename, filename="deobfuscated_lexyhub.lua"))

        if os.path.exists(final_filename):
            os.remove(final_filename)

        if output_file_from_json and os.path.exists(output_file_from_json):
            try:
                os.remove(output_file_from_json)
            except Exception:
                pass

        if os.path.exists(expected_output_path):
            try:
                os.remove(expected_output_path)
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        embed_err = discord.Embed(
            title=f"{EMOJI_INCORRECT} Error",
            description="El código no se pudo deobfuscar, vuelve a intentar o verifica si el código es luraph.",
            color=discord.Color.from_rgb(235, 59, 90)
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
            color=discord.Color.from_rgb(235, 59, 90)
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
