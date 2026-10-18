import os
import sys
import zipfile
import subprocess
import shutil
import json
import re
import time
import logging
import asyncio
import aiohttp
import discord
from discord.ext import commands

# ==================== CONFIGURACIÓN DE LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname] %(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LexyHubBot")

# ==================== CONSTANTES Y EMOJIS ====================
EMOJI_LOADING = "⏳"
EMOJI_CORRECT = "<:correct:1561435171385909288>"
EMOJI_INCORRECT = "<:incorrect:1561436020766146590>"

ZIP_FILE = "luraphv15_1_deobf.zip"
TARGET_DIR = "v15_tool_attempt_source"

if os.path.exists(ZIP_FILE) and not os.path.exists(TARGET_DIR):
    logger.info(f"Descomprimiendo {ZIP_FILE}...")
    try:
        with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
            zip_ref.extractall(TARGET_DIR)
        logger.info("Descompresión completada con éxito.")
    except Exception as e:
        logger.error(f"Error al descomprimir {ZIP_FILE}: {e}")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

@bot.event
async def on_ready():
    logger.info(f"¡Bot conectado exitosamente como {bot.user}!")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="scripts Luau | .help"
        )
    )

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Error en comando: {error}")

# ==================== MOTOR DE OPTIMIZACIÓN Y LIMPIEZA PROFUNDA ====================
class LuauOptimizer:
    @staticmethod
    def detect_version(code: str) -> str:
        code_lower = code.lower()
        if "prometheus" in code_lower or "prm_" in code_lower:
            return "Prometheus Obfuscator"
        elif "lph_" in code_lower or "luraph" in code_lower or "devirtualizing" in code_lower:
            if "v15.1" in code_lower or "path2d" in code or "15.1" in code_lower:
                return "Luraph v15.1 (Avanzado)"
            elif "v15" in code_lower or len(code) > 300:
                return "Luraph v15 Estándar"
            else:
                return "Luraph (Variante Personalizada)"
        return "No compatible / Ofuscador Desconocido"

    @staticmethod
    def deep_clean_and_fix(code: str) -> str:
        fixed_code = code.replace("if nil == 1 then", "if 1 == 1 then").replace("elseif nil == 2 then", "elseif 1 == 2 then")
        fixed_code = re.sub(r'local function\s+fn\d+\s*\(\s*\)\s*end', '-- [Función vacía removida automáticamente]', fixed_code)
        
        lines = fixed_code.splitlines()
        cleaned = []
        for line in lines:
            if "devirt:" in line or 'error("devirt:' in line or "LPH:" in line or "Prometheus" in line:
                continue
            if line.strip().startswith("--[[") and "corrupted" in line.lower():
                continue
            cleaned.append(line)
            
        result = "\n".join(cleaned)
        result = re.sub(r'\n\s*\n\s*\n+', '\n\n', result)
        return result.strip()

    @staticmethod
    def beautify(code: str) -> str:
        optimized = LuauOptimizer.deep_clean_and_fix(code)
        lines = optimized.splitlines()
        formatted = []
        indent = 0
        tab = "    "

        decrease_kw = {"end", "until", "else", "elseif"}
        increase_kw = {"do", "then", "repeat", "function"}
        starters = {"if", "for", "while", "local function", "function", "repeat"}

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped in decrease_kw or stripped.startswith(("end", "until", "else", "elseif")) or stripped == "}":
                indent = max(0, indent - 1)

            formatted.append((tab * indent) + stripped)

            lower = stripped.lower()
            is_start = any(lower.startswith(kw) for kw in starters)
            has_op = any(kw in lower for kw in increase_kw) or lower.endswith("do") or lower.endswith("then")

            if (is_start and has_op) or stripped in {"do", "repeat"} or stripped.endswith("{") or lower.startswith("else") or lower.startswith("elseif"):
                indent += 1

        return "\n".join(formatted)

    @staticmethod
    def format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

# ==================== COMANDO: .HELP ====================
@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(
        title="🛡️ Lexy Hub — Panel de Ingeniería Inversa",
        description="Suite avanzada para desofuscar, detectar y optimizar scripts de Luau (Luraph & Prometheus).",
        color=discord.Color.from_rgb(25, 25, 35)
    )
    embed.add_field(name="🔍 `.detect <URL / Adjunto>`", value="Identifica si el script usa Luraph o Prometheus.", inline=False)
    embed.add_field(name="🔓 `.luraph <URL / Adjunto>`", value="Desofusca scripts de Luraph v15/v15.1.", inline=False)
    embed.add_field(name="🔥 `.prometheus <URL / Adjunto>`", value="Desofusca scripts protegidos con Prometheus.", inline=False)
    embed.add_field(name="✨ `.beautify <URL / Adjunto>`", value="Limpia errores y re-indenta código Luau.", inline=False)
    embed.add_field(name="📥 `.get <URL>`", value="Recupera código fuente en texto plano desde enlaces externos.", inline=False)
    embed.set_footer(text="Lexy Hub Security • Enterprise Grade")
    await ctx.send(embed=embed)

# ==================== COMANDO: .DETECT ====================
@bot.command(name="detect")
async def cmd_detect(ctx, url: str = None):
    has_att = bool(ctx.message.attachments)
    if not has_att and not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Adjunta un archivo o provee una URL.", color=discord.Color.red()))
        return

    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Analizando...", description="Escaneando firmas de ofuscación...", color=discord.Color.blue()))

    try:
        source_link, code = "Archivo adjunto", ""
        if has_att:
            att = ctx.message.attachments[0]
            source_link = att.url
            code = (await att.read()).decode("utf-8", errors="ignore")
        else:
            if not url.startswith(("http://", "https://")): url = "https://" + url
            source_link = url
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as res:
                    if res.status != 200:
                        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error HTTP", color=discord.Color.red()))
                        return
                    code = (await res.read()).decode("utf-8", errors="ignore")

        detected = LuauOptimizer.detect_version(code)
        embed_desc = (
            f"## {EMOJI_CORRECT} SIGNATURE DETECTED\n"
            f"**Ofuscador Identificado:**\n```ini\n[{detected}]\n```\n"
            f"Source: {source_link}"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))
        await msg.edit(content=None, embed=embed)
    except Exception as e:
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .GET ====================
@bot.command(name="get")
async def cmd_get(ctx, url: str = None):
    if not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Proporciona una URL válida.", color=discord.Color.red()))
        return
    if not url.startswith(("http://", "https://")): url = "https://" + url

    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Conectando...", color=discord.Color.blue()))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as res:
                if res.status != 200:
                    await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error HTTP", color=discord.Color.red()))
                    return
                content = await res.text()

        if len(content) <= 1900:
            await msg.delete()
            await ctx.send(f"```lua\n{content}\n```")
        else:
            path = f"get_{ctx.author.id}.lua"
            with open(path, "w", encoding="utf-8") as f: f.write(content)
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_CORRECT} Extraído", color=discord.Color.green()))
            await ctx.send(file=discord.File(path, filename="contenido.lua"))
            os.remove(path)
    except Exception as e:
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .BEAUTIFY ====================
@bot.command(name="beautify")
async def cmd_beautify(ctx, url: str = None):
    has_att = bool(ctx.message.attachments)
    if not has_att and not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Adjunta un archivo o provee un enlace.", color=discord.Color.red()))
        return

    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Optimizando...", description="Formateando código...", color=discord.Color.blue()))

    try:
        source_link, code = "Archivo adjunto", ""
        if has_att:
            att = ctx.message.attachments[0]
            source_link = att.url
            input_size = att.size
            code = (await att.read()).decode("utf-8", errors="ignore")
        else:
            if not url.startswith(("http://", "https://")): url = "https://" + url
            source_link = url
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as res:
                    if res.status != 200:
                        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", color=discord.Color.red()))
                        return
                    data = await res.read()
                    input_size = len(data)
                    code = data.decode("utf-8", errors="ignore")

        ready_code = LuauOptimizer.beautify(code)
        final_text = f"-- Deobfuscado por Lexy Deobf\n\n{ready_code}"

        path = "executable_script.lua"
        with open(path, "w", encoding="utf-8") as f: f.write(final_text)

        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time

        preview_lines = final_text.splitlines()[:8]
        preview = "\n".join(preview_lines)
        if len(final_text.splitlines()) > 8: preview += "\n--"

        embed_desc = (
            f"## {EMOJI_CORRECT} LUA SCRIPT BEAUTIFIED\n"
            f"**Output Preview**\n"
            f"```lua\n{preview}\n```\n"
            f"Source: {source_link}\n"
            f"-# input: {LuauOptimizer.format_size(input_size)} · output: {LuauOptimizer.format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            f"**Output File:**"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))

        await msg.delete()
        # El archivo va junto en el ctx.send, lo que en Discord lo coloca visualmente abajo del embed
        await ctx.send(embed=embed, file=discord.File(path, filename="executable_script.lua"))
        if os.path.exists(path): os.remove(path)
    except Exception as e:
        logger.error(f"Error en .beautify: {e}")
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .LURAPH ====================
@bot.command(name="luraph")
async def cmd_luraph(ctx, url: str = None):
    input_file = f"input_{ctx.author.id}.lua"
    output_file = f"output_{ctx.author.id}.lua"
    out_dir = "output"

    has_att = bool(ctx.message.attachments)
    if not has_att and not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Falta archivo adjunto o enlace.", color=discord.Color.red()))
        return

    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Desofuscando Luraph...", description="Procesando capas de virtualización...", color=discord.Color.from_rgb(0, 128, 255)))

    try:
        source_link = "Archivo adjunto"
        if has_att:
            att = ctx.message.attachments[0]
            await att.save(input_file)
            source_link = att.url
            input_size = att.size
        else:
            if not url.startswith(("http://", "https://")): url = "https://" + url
            source_link = url
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as res:
                    if res.status != 200:
                        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", color=discord.Color.red()))
                        return
                    code_data = await res.read()
                    input_size = len(code_data)
            with open(input_file, "wb") as f: f.write(code_data)

        node_bin = shutil.which("node") or shutil.which("nodejs") or "node"
        cmd = [node_bin, "v15_tool_attempt_source/v15_tool_attempt_source/deob.js", input_file, output_file]

        process = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=65)

        raw_out = process.stdout.strip()
        json_path = None
        try:
            js = json.loads(raw_out[raw_out.find('{'):raw_out.rfind('}')+1])
            if js.get("success"): json_path = js.get("output")
        except: pass

        result_code = ""
        expected_path = os.path.join(out_dir, input_file)

        if json_path and os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8", errors="ignore") as f: result_code = f.read()
        elif os.path.exists(expected_path):
            with open(expected_path, "r", encoding="utf-8", errors="ignore") as f: result_code = f.read()
        elif os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8", errors="ignore") as f: result_code = f.read()

        if not result_code.strip():
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Fallo", description="El script contiene protecciones pesadas.", color=discord.Color.red()))
            return

        ready_code = LuauOptimizer.beautify(result_code)
        final_text = f"-- Deobfuscado por Lexy Deobf\n\n{ready_code}"

        path = "executable_script.lua"
        with open(path, "w", encoding="utf-8") as f: f.write(final_text)

        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time

        preview_lines = final_text.splitlines()[:8]
        preview = "\n".join(preview_lines)
        if len(final_text.splitlines()) > 8: preview += "\n--"

        embed_desc = (
            f"## {EMOJI_CORRECT} LURAPH V15 DEOBFUSCATED\n"
            f"**Output Preview**\n"
            f"```lua\n{preview}\n```\n"
            f"Source: {source_link}\n"
            f"-# input: {LuauOptimizer.format_size(input_size)} · output: {LuauOptimizer.format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            f"**Output File:**"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))

        await msg.delete()
        await ctx.send(embed=embed, file=discord.File(path, filename="executable_script.lua"))

        for p in [path, input_file, output_file, json_path, expected_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass

    except Exception as e:
        logger.error(f"Error crítico en .luraph: {e}")
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error Crítico", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .PROMETHEUS ====================
@bot.command(name="prometheus")
async def cmd_prometheus(ctx, url: str = None):
    input_file = f"prom_input_{ctx.author.id}.lua"
    output_file = f"prom_output_{ctx.author.id}.lua"

    has_att = bool(ctx.message.attachments)
    if not has_att and not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description="Falta archivo adjunto o enlace de Prometheus.", color=discord.Color.red()))
        return

    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Desofuscando Prometheus...", description="Procesando desofuscación...", color=discord.Color.from_rgb(255, 140, 0)))

    try:
        source_link = "Archivo adjunto"
        if has_att:
            att = ctx.message.attachments[0]
            await att.save(input_file)
            source_link = att.url
            input_size = att.size
        else:
            if not url.startswith(("http://", "https://")): url = "https://" + url
            source_link = url
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as res:
                    if res.status != 200:
                        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", color=discord.Color.red()))
                        return
                    code_data = await res.read()
                    input_size = len(code_data)
            with open(input_file, "wb") as f: f.write(code_data)

        node_bin = shutil.which("node") or shutil.which("nodejs") or "node"
        cmd = [node_bin, "prometheus_tool/deob.js", input_file, output_file]

        process = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=65)

        result_code = ""
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
                result_code = f.read()
        elif process.stdout.strip():
            result_code = process.stdout.strip()

        if not result_code.strip():
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Fallo", description="No se pudo desofuscar el script de Prometheus.", color=discord.Color.red()))
            return

        ready_code = LuauOptimizer.beautify(result_code)
        final_text = f"-- Deobfuscado por Lexy Deobf (Prometheus)\n\n{ready_code}"

        path = "executable_script.lua"
        with open(path, "w", encoding="utf-8") as f: f.write(final_text)

        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time

        preview_lines = final_text.splitlines()[:8]
        preview = "\n".join(preview_lines)
        if len(final_text.splitlines()) > 8: preview += "\n--"

        embed_desc = (
            f"## {EMOJI_CORRECT} PROMETHEUS DEOBFUSCATED\n"
            f"**Output Preview**\n"
            f"```lua\n{preview}\n```\n"
            f"Source: {source_link}\n"
            f"-# input: {LuauOptimizer.format_size(input_size)} · output: {LuauOptimizer.format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            f"**Output File:**"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(255, 140, 0))

        await msg.delete()
        await ctx.send(embed=embed, file=discord.File(path, filename="executable_script.lua"))

        for p in [path, input_file, output_file]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass

    except Exception as e:
        logger.error(f"Error crítico en .prometheus: {e}")
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error Crítico", description=str(e)[:200], color=discord.Color.red()))

# ==================== INICIO DEL BOT ====================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.critical("¡Falta la variable de entorno DISCORD_TOKEN!")
else:
    bot.run(TOKEN)
