import os
import sys
import zipfile
import subprocess
import shutil
import json
import re
import time
import tempfile
import logging
import asyncio
import aiohttp
import discord
from discord.ext import commands

# ==================== CONFIGURACIÓN DE LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LexyHubBot")

# ==================== CONSTANTES Y EMOJIS ====================
EMOJI_LOADING = "⏳"
EMOJI_CORRECT = "<:correct:1561435171385909288>"
EMOJI_INCORRECT = "<:incorrect:1561436020766146590>"

# --- DESCOMPRESIÓN AUTOMÁTICA DE HERRAMIENTAS ---
LURAPH_ZIP = "luraphv15_1_deobf.zip"
LURAPH_DIR = "v15_tool_attempt_source"

PROM_ZIP = "Prometheus-Deobfuscator-main.zip"
PROM_DIR = "Prometheus-Deobfuscator-main"

MOON_ZIP = "moonsec-v3.zip"
MOON_DIR = "moonsec-v3"
MOON_DLL = os.path.join(MOON_DIR, "bin", "Release", "net9.0", "MoonsecDeobfuscator.dll")
MOON_JAR = os.path.join(MOON_DIR, "deps", "unluac", "unluac.jar")

if os.path.exists(LURAPH_ZIP) and not os.path.exists(LURAPH_DIR):
    logger.info(f"Descomprimiendo {LURAPH_ZIP}...")
    try:
        with zipfile.ZipFile(LURAPH_ZIP, 'r') as zip_ref:
            zip_ref.extractall(LURAPH_DIR)
        logger.info("Luraph descomprimido con éxito.")
    except Exception as e:
        logger.error(f"Error al descomprimir {LURAPH_ZIP}: {e}")

if os.path.exists(PROM_ZIP) and not os.path.exists(PROM_DIR):
    logger.info(f"Descomprimiendo {PROM_ZIP}...")
    try:
        with zipfile.ZipFile(PROM_ZIP, 'r') as zip_ref:
            zip_ref.extractall(".")
        logger.info("Prometheus descomprimido con éxito.")
    except Exception as e:
        logger.error(f"Error al descomprimir {PROM_ZIP}: {e}")

if os.path.exists(MOON_ZIP) and not os.path.exists(MOON_DIR):
    logger.info(f"Descomprimiendo {MOON_ZIP}...")
    try:
        with zipfile.ZipFile(MOON_ZIP, 'r') as zip_ref:
            zip_ref.extractall(".")
        logger.info("MoonSec V3 descomprimido con éxito.")
    except Exception as e:
        logger.error(f"Error al descomprimir {MOON_ZIP}: {e}")

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

# ==================== UTILIDAD PARA OBTENER ARCHIVO O URL ====================
async def get_code_and_source(ctx, url: str = None):
    code = ""
    source_link = "Desconocido"
    input_size = 0

    # 1. Verificar si hay archivo adjunto en el mensaje actual
    if ctx.message.attachments:
        att = ctx.message.attachments[0]
        source_link = att.url
        input_size = att.size
        code = (await att.read()).decode("utf-8", errors="ignore")
        return code, source_link, input_size

    # 2. Verificar si está respondiendo a un mensaje que tiene archivo adjunto
    if ctx.message.reference and ctx.message.reference.message_id:
        try:
            ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if ref_msg.attachments:
                att = ref_msg.attachments[0]
                source_link = att.url
                input_size = att.size
                code = (await att.read()).decode("utf-8", errors="ignore")
                return code, source_link, input_size
        except Exception:
            pass

    # 3. Verificar si se proporcionó una URL
    if url:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        source_link = url
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as res:
                if res.status != 200:
                    raise Exception(f"Error HTTP al acceder a la URL: {res.status}")
                data = await res.read()
                input_size = len(data)
                code = data.decode("utf-8", errors="ignore")
        return code, source_link, input_size

    raise Exception("No se encontró ningún archivo adjunto, mensaje respondido con archivo ni URL válida.")

# ==================== MOTOR DE OPTIMIZACIÓN Y LIMPIEZA PROFUNDA ====================
class LuauOptimizer:
    @staticmethod
    def detect_version(code: str) -> str:
        code_lower = code.lower()
        if re.search(r"protected (?:with|using) moonsec v3\b", code[:3000], re.I):
            return "MoonSec V3"
        elif "moonsec" in code_lower:
            return "MoonSec (V2 / variante no soportada)"
        elif "prometheus" in code_lower or "prm_" in code_lower or "pdeobf" in code_lower:
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
        description="Suite avanzada para desofuscar, detectar y optimizar scripts de Luau (Luraph, Prometheus & MoonSec V3).",
        color=discord.Color.from_rgb(25, 25, 35)
    )
    embed.add_field(name="🔍 `.detect <URL / Adjunto / Responder>`", value="Identifica el ofuscador del script.", inline=False)
    embed.add_field(name="🔓 `.luraph <URL / Adjunto / Responder>`", value="Desofusca scripts de Luraph v15/v15.1.", inline=False)
    embed.add_field(name="🔥 `.prometheus <URL / Adjunto / Responder>`", value="Desofusca scripts protegidos con Prometheus.", inline=False)
    embed.add_field(name="🌙 `.moonveil <URL / Adjunto / Responder>`", value="Desofusca scripts protegidos con MoonSec V3.", inline=False)
    embed.add_field(name="📋 `.list`", value="Muestra la lista de desofuscadores y herramientas integradas.", inline=False)
    embed.add_field(name="✨ `.beautify <URL / Adjunto / Responder>`", value="Limpia errores y re-indenta código Luau.", inline=False)
    embed.add_field(name="📥 `.get <URL>`", value="Recupera código fuente en texto plano desde enlaces externos.", inline=False)
    embed.set_footer(text="Lexy Hub Security • Enterprise Grade")
    await ctx.send(embed=embed)

# ==================== COMANDO: .LIST ====================
@bot.command(name="list")
async def cmd_list(ctx):
    embed = discord.Embed(
        title="📂 Lexy Hub — Desofuscadores Disponibles",
        description="Lista actual de motores de ingeniería inversa integrados en el sistema:",
        color=discord.Color.from_rgb(0, 204, 102)
    )
    embed.add_field(
        name="1️⃣ Luraph Deobfuscator",
        value="• **Versiones:** v15 y v15.1\n• **Comando:** `.luraph` (adjunto, URL o respondiendo)\n• **Estado:** `Activo`",
        inline=False
    )
    embed.add_field(
        name="2️⃣ Prometheus Deobfuscator",
        value="• **Versiones:** CLI Estándar\n• **Comando:** `.prometheus` (adjunto, URL o respondiendo)\n• **Estado:** `Activo`",
        inline=False
    )
    embed.add_field(
        name="3️⃣ MoonSec V3 Deobfuscator",
        value="• **Versiones:** MoonSec V3 (V2 no soportado)\n• **Comando:** `.moonveil` (adjunto, URL o respondiendo)\n• **Estado:** `Activo`",
        inline=False
    )
    embed.add_field(
        name="4️⃣ Luau Beautifier & Fixer",
        value="• **Función:** Limpieza y optimización\n• **Comando:** `.beautify` (adjunto, URL o respondiendo)\n• **Estado:** `Activo`",
        inline=False
    )
    embed.set_footer(text="Lexy Hub Security • Herramientas de Alto Rendimiento")
    await ctx.send(embed=embed)

# ==================== COMANDO: .DETECT ====================
@bot.command(name="detect")
async def cmd_detect(ctx, url: str = None):
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Analizando...", description="Escaneando firmas de ofuscación...", color=discord.Color.blue()))
    try:
        code, source_link, _ = await get_code_and_source(ctx, url)
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
    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Optimizando...", description="Formateando código...", color=discord.Color.blue()))

    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        ready_code = LuauOptimizer.beautify(code)
        final_text = f"-- Deobfuscado por Lexy Deobf\n\n{ready_code}"

        path = f"executable_script_{ctx.author.id}.lua"
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
        # Enviar embed primero y el archivo en un mensaje separado abajo
        await ctx.send(embed=embed)
        await ctx.send(file=discord.File(path, filename="executable_script.lua"))

        if os.path.exists(path): os.remove(path)
    except Exception as e:
        logger.error(f"Error en .beautify: {e}")
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .LURAPH ====================
@bot.command(name="luraph")
async def cmd_luraph(ctx, url: str = None):
    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Desofuscando Luraph...", description="Procesando capas de virtualización...", color=discord.Color.from_rgb(0, 128, 255)))

    input_file = f"input_{ctx.author.id}.lua"
    output_file = f"output_{ctx.author.id}.lua"
    out_dir = "output"

    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

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

        path = f"executable_script_{ctx.author.id}.lua"
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
        # Enviar embed primero y el archivo en un mensaje separado abajo
        await ctx.send(embed=embed)
        await ctx.send(file=discord.File(path, filename="executable_script.lua"))

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
    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Desofuscando Prometheus...", description="Procesando desofuscación...", color=discord.Color.from_rgb(0, 204, 102)))

    input_file = f"prom_input_{ctx.author.id}.lua"
    output_file = f"prom_output_{ctx.author.id}.lua"

    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        node_bin = shutil.which("node") or shutil.which("nodejs") or "node"
        cmd = [node_bin, "Prometheus-Deobfuscator-main/bin/pdeobf.js", input_file, output_file]

        process = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=65)

        result_code = ""
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
                result_code = f.read()
        elif process.stdout.strip():
            result_code = process.stdout.strip()

        if not result_code.strip():
            err_output = process.stderr.strip() or process.stdout.strip() or "Sin detalles"
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Fallo", description=f"No se pudo desofuscar con Prometheus.\n```{err_output[:150]}```", color=discord.Color.red()))
            return

        ready_code = LuauOptimizer.beautify(result_code)
        final_text = f"-- Deobfuscado por Lexy Deobf\n\n{ready_code}"

        path = f"executable_script_{ctx.author.id}.lua"
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
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))

        await msg.delete()
        # Enviar embed primero y el archivo en un mensaje separado abajo
        await ctx.send(embed=embed)
        await ctx.send(file=discord.File(path, filename="executable_script.lua"))

        for p in [path, input_file, output_file]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass

    except Exception as e:
        logger.error(f"Error crítico en .prometheus: {e}")
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error Crítico", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .MOONVEIL (MoonSec V3) ====================
async def run_stage(args, deadline: float, label: str):
    """Ejecuta una etapa del pipeline respetando un presupuesto de tiempo compartido."""
    proc = await asyncio.create_subprocess_exec(
        *[str(a) for a in args],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    remaining = deadline - asyncio.get_running_loop().time()
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), max(1, remaining))
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"{label}: tiempo agotado")
    if proc.returncode:
        diag = (stderr or stdout).decode("utf-8", "replace").strip()
        raise RuntimeError(f"{label} falló: {diag[:800]}")
    return stdout, stderr

@bot.command(name="moonveil", aliases=["moonsec", "msd"])
async def cmd_moonveil(ctx, url: str = None):
    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Desofuscando MoonSec V3...", description="Devirtualizando bytecode...", color=discord.Color.from_rgb(120, 80, 255)))

    work_dir = tempfile.mkdtemp(prefix=f"moon_{ctx.author.id}_")
    path = f"executable_script_{ctx.author.id}.lua"

    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)

        if not re.search(r"protected (?:with|using) MoonSec V3\b", code[:3000], re.I):
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} No compatible", description="No se detectó el banner de **MoonSec V3** (MoonSec V2 no está soportado).", color=discord.Color.red()))
            return

        dotnet_bin = shutil.which("dotnet") or os.path.expanduser("~/.dotnet/dotnet")
        java_bin = os.getenv("MOONSEC_JAVA") or shutil.which("java")
        missing = []
        if not dotnet_bin or not os.path.exists(dotnet_bin): missing.append(".NET 9 runtime (`dotnet`)")
        if not java_bin: missing.append("Java 8+ (`java`)")
        if not os.path.isfile(MOON_DLL) or not os.path.isfile(MOON_JAR):
            missing.append(f"archivos de `{MOON_ZIP}` (¿está junto al bot?)")
        if missing:
            await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Falta en el servidor", description="\n".join(f"• {m}" for m in missing), color=discord.Color.red()))
            return

        input_file = os.path.join(work_dir, "input.lua")
        bytecode_file = os.path.join(work_dir, "recovered.luac")
        output_file = os.path.join(work_dir, "deobfuscated.lua")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        deadline = asyncio.get_running_loop().time() + 300

        # Etapa 1: MoonSec V3 -> bytecode Lua 5.1
        await run_stage([dotnet_bin, MOON_DLL, "-dev", "-i", input_file, "-o", bytecode_file], deadline, "MoonSec")
        if not os.path.isfile(bytecode_file) or open(bytecode_file, "rb").read(5) != b"\x1bLua\x51":
            raise RuntimeError("MoonSec no generó bytecode Lua 5.1 válido.")

        # Etapa 2: bytecode -> código fuente con unluac
        await run_stage([java_bin, "-Xmx512m", "-jar", MOON_JAR, "--nodebug", "-o", output_file, bytecode_file], deadline, "unluac")
        if not os.path.isfile(output_file):
            raise RuntimeError("unluac no generó salida.")
        with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        if not result_code.strip():
            raise RuntimeError("unluac produjo una salida vacía.")

        ready_code = LuauOptimizer.beautify(result_code)
        final_text = f"-- Deobfuscado por Lexy Deobf\n\n{ready_code}"

        with open(path, "w", encoding="utf-8") as f: f.write(final_text)

        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time

        preview_lines = final_text.splitlines()[:8]
        preview = "\n".join(preview_lines)
        if len(final_text.splitlines()) > 8: preview += "\n--"

        embed_desc = (
            f"## {EMOJI_CORRECT} MOONSEC V3 DEOBFUSCATED\n"
            f"**Output Preview**\n"
            f"```lua\n{preview}\n```\n"
            f"Source: {source_link}\n"
            f"-# input: {LuauOptimizer.format_size(input_size)} · output: {LuauOptimizer.format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            f"**Output File:**"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))

        await msg.delete()
        await ctx.send(embed=embed)
        await ctx.send(file=discord.File(path, filename="executable_script.lua"))

    except Exception as e:
        logger.error(f"Error crítico en .moonveil: {e}")
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_INCORRECT} Error Crítico", description=f"```{str(e)[:400]}```", color=discord.Color.red()))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if os.path.exists(path):
            try: os.remove(path)
            except: pass

# ==================== INICIO DEL BOT ====================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.critical("¡Falta la variable de entorno DISCORD_TOKEN!")
else:
    bot.run(TOKEN)
