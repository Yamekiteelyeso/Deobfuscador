import os
import zipfile
import subprocess
import shutil
import json
import re
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

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"¡El bot está en línea y conectado como: {bot.user}!")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="scripts | .help"))

# ==================== LIMPIADOR PROFESIONAL DE CÓDIGO ====================
def clean_lua_code(code: str) -> str:
    """Remueve líneas de error residuales, trazas de devirtualización y comentarios basura."""
    lines = code.splitlines()
    cleaned_lines = []
    
    for line in lines:
        if "devirt: index nil" in line or "error(\"devirt:" in line or "LPH:" in line:
            continue
        cleaned_lines.append(line)
        
    cleaned_code = "\n".join(cleaned_lines)
    cleaned_code = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_code)
    return cleaned_code.strip()

# ==================== FORMATO LUA (BEAUTIFY AVANZADO) ====================
def advanced_beautify(code: str) -> str:
    """Ordena, formatea y re-indenta código Lua/Luau de manera limpia y estructurada."""
    cleaned = clean_lua_code(code)
    lines = cleaned.splitlines()
    formatted = []
    indent_level = 0
    tab = "    "

    # Palabras clave de control de flujo
    decrease_keywords = {"end", "until", "else", "elseif"}
    increase_keywords = {"do", "then", "repeat", "function"}
    block_starters = {"if", "for", "while", "local function", "function", "repeat"}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        # Disminuir indentación si la línea cierra un bloque
        if stripped in decrease_keywords or stripped.startswith(("end", "until", "else", "elseif")) or stripped == "}":
            indent_level = max(0, indent_level - 1)

        formatted.append((tab * indent_level) + stripped)

        # Aumentar indentación si la línea abre un nuevo bloque
        lower = stripped.lower()
        is_block_start = any(lower.startswith(kw) for kw in block_starters)
        has_opener = any(kw in lower for kw in increase_keywords) or lower.endswith("do") or lower.endswith("then")
        
        if (is_block_start and has_opener) or stripped in {"do", "repeat"} or stripped.endswith("{") or lower.startswith("else") or lower.startswith("elseif"):
            indent_level += 1

    return "\n".join(formatted)

# ==================== COMANDO: .HELP ====================
@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="🛡️ Lexy Hub — Centro de Herramientas",
        description="Plataforma avanzada de ingeniería inversa, desofuscación y optimización de scripts en Luau.",
        color=discord.Color.from_rgb(30, 30, 45)
    )
    
    embed.add_field(
        name="🔓 `.luraph <URL / Adjunto>`",
        value="Desofusca scripts protegidos con Luraph v15 eliminando capas de virtualización.",
        inline=False
    )
    embed.add_field(
        name="✨ `.beautify <URL / Adjunto>`",
        value="Formatea, re-indenta y limpia código Luau para hacerlo legible.",
        inline=False
    )
    embed.add_field(
        name="📥 `.get <URL>`",
        value="Extrae y muestra el contenido de texto plano directamente desde URLs externas.",
        inline=False
    )
    
    embed.set_footer(text="Lexy Hub Security • High Performance Tools")
    await ctx.send(embed=embed)

# ==================== COMANDO: .GET ====================
@bot.command(name="get")
async def cmd_get(ctx, url: str = None):
    if not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Debes proporcionar una URL válida.", color=discord.Color.red()))
        return

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Conectando...", color=discord.Color.blue()))

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as res:
                if res.status != 200:
                    await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error HTTP: {res.status}", color=discord.Color.red()))
                    return
                content = await res.text()

        if len(content) <= 1900:
            await msg.delete()
            await ctx.send(f"```lua\n{content}\n```")
        else:
            path = f"get_{ctx.author.id}.lua"
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_CORRECT} Descargado", description="El archivo adjunto contiene el texto completo.", color=discord.Color.green()))
            await ctx.send(file=discord.File(path, filename="contenido.lua"))
            os.remove(path)
    except Exception as e:
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Fallo", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .BEAUTIFY ====================
@bot.command(name="beautify")
async def cmd_beautify(ctx, url: str = None):
    has_att = bool(ctx.message.attachments)
    if not has_att and not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Adjunta un archivo o provee un enlace válido.", color=discord.Color.red()))
        return

    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Embelleciendo...", color=discord.Color.blue()))

    try:
        source, code = "", ""
        if has_att:
            att = ctx.message.attachments[0]
            source = f"[`{att.filename}`]({att.url})"
            code = (await att.read()).decode("utf-8", errors="ignore")
        else:
            if not url.startswith(("http://", "https://")): url = "https://" + url
            source = f"[Enlace Fuente]({url})"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as res:
                    if res.status != 200:
                        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="No se pudo acceder a la URL.", color=discord.Color.red()))
                        return
                    code = await res.text()

        formatted_code = advanced_beautify(code)
        final_text = f"-- Formateado y Limpiado por Lexy Hub\n\n{formatted_code}"
        
        path = "beautified_lexyhub.lua"
        with open(path, "w", encoding="utf-8") as f:
            f.write(final_text)

        preview = "\n".join(final_text.splitlines()[:6])
        if len(final_text.splitlines()) > 6:
            preview += "\n..."

        embed = discord.Embed(title=f"{EMOJI_CORRECT} SUCCESSFULLY BEAUTIFIED", color=discord.Color.from_rgb(0, 204, 102))
        embed.add_field(name="🔗 Fuente", value=source, inline=False)
        embed.add_field(name="📄 Preview del Código", value=f"```lua\n{preview}\n```", inline=False)
        embed.set_footer(text="Lexy Hub Protection & Tools")

        await msg.edit(embed=embed)
        await ctx.send(file=discord.File(path, filename="beautified.lua"))
        os.remove(path)
    except Exception as e:
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .LURAPH ====================
@bot.command(name="luraph")
async def cmd_luraph(ctx, url: str = None):
    input_file = f"input_{ctx.author.id}.lua"
    output_file = f"output_{ctx.author.id}.lua"
    out_dir = "output"

    has_att = bool(ctx.message.attachments)
    if not has_att and not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Falta un archivo adjunto o enlace de Luraph.", color=discord.Color.red()))
        return

    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Desofuscando...", description="Analizando capas de virtualización de Luraph v15...", color=discord.Color.from_rgb(0, 128, 255)))

    try:
        source = "Archivo adjunto"
        if has_att:
            att = ctx.message.attachments[0]
            await att.save(input_file)
            source = f"[`{att.filename}`]({att.url})"
        else:
            if not url.startswith(("http://", "https://")): url = "https://" + url
            source = f"[Enlace Fuente]({url})"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as res:
                    if res.status != 200:
                        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="No se pudo descargar el script de la URL.", color=discord.Color.red()))
                        return
                    code_data = await res.text()
            with open(input_file, "w", encoding="utf-8") as f:
                f.write(code_data)

        node_bin = shutil.which("node") or shutil.which("nodejs") or "node"
        cmd = [node_bin, "v15_tool_attempt_source/v15_tool_attempt_source/deob.js", input_file, output_file]
        
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        raw_out = process.stdout.strip()
        json_path = None
        try:
            js = json.loads(raw_out[raw_out.find('{'):raw_out.rfind('}')+1])
            if js.get("success"): json_path = js.get("output")
        except:
            pass

        result_code = ""
        expected_path = os.path.join(out_dir, input_file)
        
        if json_path and os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8", errors="ignore") as f: result_code = f.read()
        elif os.path.exists(expected_path):
            with open(expected_path, "r", encoding="utf-8", errors="ignore") as f: result_code = f.read()
        elif os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8", errors="ignore") as f: result_code = f.read()

        if not result_code.strip():
            err_msg = process.stderr.strip() or raw_out or "El script contenía protecciones extremas anti-emulación."
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Fallo de Desofuscación", description="El script posee protecciones pesadas o un bucle anti-análisis.", color=discord.Color.red()))
            try:
                await ctx.author.send(f"⚠️ **Log técnico del fallo:**\n```{err_msg[:1900]}```")
            except:
                pass
            return

        cleaned = clean_lua_code(result_code)
        final_text = f"-- Desofuscado y Limpiado por Lexy Hub\n\n{cleaned}"
        
        path = "deobfuscated_lexyhub.lua"
        with open(path, "w", encoding="utf-8") as f:
            f.write(final_text)

        preview = "\n".join(final_text.splitlines()[:6])
        if len(final_text.splitlines()) > 6:
            preview += "\n..."

        embed = discord.Embed(title=f"{EMOJI_CORRECT} SUCCESSFULLY FETCHED", color=discord.Color.from_rgb(0, 204, 102))
        embed.add_field(name="🔗 Fuente", value=source, inline=False)
        embed.add_field(name="📄 Preview del Código", value=f"```lua\n{preview}\n```", inline=False)
        embed.set_footer(text="Lexy Hub Protection & Tools")

        await msg.edit(embed=embed)
        await ctx.send(file=discord.File(path, filename="deobfuscated.lua"))

        for p in [path, input_file, output_file, json_path, expected_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass

    except Exception as e:
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error Crítico", description=str(e)[:200], color=discord.Color.red()))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound): return

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN: bot.run(TOKEN)
