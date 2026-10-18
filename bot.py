import os
import sys
import zipfile
import subprocess
import shutil
import json
import re
import time
import tempfile
import signal
import logging
import asyncio
import aiohttp
import discord
from discord.ext import commands

# ==================== CONFIGURACIÓN DE LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LexyHubBot")

# ==================== CONSTANTES Y EMOJIS ====================
EMOJI_LOADING = "<a:loading:1561435149793493166>"
EMOJI_CORRECT = "<:correct:1561435171385909288>"
EMOJI_ERROR = "<:error:1561510204393136209>"

# --- DESCOMPRESIÓN AUTOMÁTICA DE HERRAMIENTAS ---
LURAPH_ZIP = "luraphv15_1_deobf.zip"
LURAPH_DIR = "v15_tool_attempt_source"

PROM_ZIP = "Prometheus-Deobfuscator-main.zip"
PROM_DIR = "Prometheus-Deobfuscator-main"

MOON_ZIP = "moonsec-v3.zip"
MOON_DIR = "moonsec-v3"
MOON_DLL = os.path.join(MOON_DIR, "bin", "Release", "net9.0", "MoonsecDeobfuscator.dll")
MOON_JAR = os.path.join(MOON_DIR, "deps", "unluac", "unluac.jar")

LURAPH15_ZIP = "luraphv15.zip"
LURAPH15_DIR = "Deobfuscator"
LURAPH15_BIN = os.path.join(LURAPH15_DIR, "deobf", "bin")
LURAPH15_SCRIPT = os.path.join(LURAPH15_DIR, "deobf", "deob.py")
LURAPH15_HEADER = re.compile(r"This file was protected using Luraph Obfuscator v(\d+)(?:\.(\d+))?", re.I)
LURAPH15_SHAPE = re.compile(r"\[\d+\]=(?:bit32|buffer|string|table|math)\.\w+")

GOOFY_ZIP = "goofyscator-deobf.zip"
GOOFY_DIR = "goofyscator-deobf"
GOOFY_ENGINES = os.path.join(GOOFY_DIR, "engines")
GOOFY_BIN = os.path.join(GOOFY_ENGINES, "deobfuscator", "deobf", "bin")
GOOFY_BANNER = re.compile(r"^--[^\n]*protected by goofyscator V11 BETA-1\b", re.I)

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

if os.path.exists(GOOFY_ZIP) and not os.path.exists(GOOFY_DIR):
    logger.info(f"Descomprimiendo {GOOFY_ZIP}...")
    try:
        with zipfile.ZipFile(GOOFY_ZIP, 'r') as zip_ref:
            zip_ref.extractall(".")
        logger.info("Goofyscator descomprimido con éxito.")
    except Exception as e:
        logger.error(f"Error al descomprimir {GOOFY_ZIP}: {e}")

if os.path.exists(LURAPH15_ZIP) and not os.path.exists(LURAPH15_DIR):
    logger.info(f"Descomprimiendo {LURAPH15_ZIP}...")
    try:
        with zipfile.ZipFile(LURAPH15_ZIP, 'r') as zip_ref:
            zip_ref.extractall(".")
        logger.info("Luraph v15 descomprimido con éxito.")
    except Exception as e:
        logger.error(f"Error al descomprimir {LURAPH15_ZIP}: {e}")

if os.path.isdir(LURAPH15_BIN):
    # extractall() no conserva permisos de ejecución.
    for exe in ("luau", "luau-ast"):
        exe_path = os.path.join(LURAPH15_BIN, exe)
        if os.path.isfile(exe_path):
            try: os.chmod(exe_path, 0o755)
            except Exception as e: logger.error(f"No se pudo dar permisos a {exe_path}: {e}")

if os.path.isdir(GOOFY_ENGINES):
    # El zip no trae package.json: sin "type": "module" los .ts/.mjs no resuelven sus imports.
    try:
        pkg = os.path.join(GOOFY_ENGINES, "package.json")
        if not os.path.exists(pkg):
            with open(pkg, "w", encoding="utf-8") as f:
                f.write('{"type":"module"}\n')
        # extractall() no conserva permisos de ejecución de los binarios de Luau.
        for exe in ("luau", "luau-ast"):
            exe_path = os.path.join(GOOFY_BIN, exe)
            if os.path.isfile(exe_path):
                os.chmod(exe_path, 0o755)
    except Exception as e:
        logger.error(f"Error preparando Goofyscator: {e}")

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
    # .deobf ya descargó el archivo: lo reutiliza el comando al que delega.
    cached = getattr(ctx, "_lexy_cache", None)
    if cached:
        return cached

    code = ""
    source_link = "Desconocido"
    input_size = 0

    # 1. Verificar si hay archivo adjunto en el mensaje actual
    if ctx.message.attachments:
        att = ctx.message.attachments[0]
        source_link = att.url
        input_size = att.size
        code = (await att.read()).decode("utf-8-sig", errors="ignore")
        return code, source_link, input_size

    # 2. Verificar si está respondiendo a un mensaje que tiene archivo adjunto
    if ctx.message.reference and ctx.message.reference.message_id:
        try:
            ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if ref_msg.attachments:
                att = ref_msg.attachments[0]
                source_link = att.url
                input_size = att.size
                code = (await att.read()).decode("utf-8-sig", errors="ignore")
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
                code = data.decode("utf-8-sig", errors="ignore")
        return code, source_link, input_size

    raise Exception("No se encontró ningún archivo adjunto, mensaje respondido con archivo ni URL válida.")

# ==================== MOTOR DE OPTIMIZACIÓN Y LIMPIEZA PROFUNDA ====================
class LuauOptimizer:
    @staticmethod
    def identify(code: str):
        """Devuelve (etiqueta, comando, evidencia). El comando es None si no hay soporte."""
        code_lower = code.lower()
        luraph_header = LURAPH15_HEADER.search(code[:500])
        moon = re.search(r"protected (?:with|using) moonsec v3\b", code[:3000], re.I)
        head = code.lstrip("\ufeff \t\r\n")

        if moon:
            return "MoonSec V3", "moonveil", "banner «protected with MoonSec V3»"
        if GOOFY_BANNER.search(head[:3000]):
            return "Goofyscator V11 BETA-1", "goofy", "banner «protected by goofyscator V11 BETA-1»"
        if luraph_header and luraph_header.group(1) == "15":
            # El encabezado de Luraph es definitivo: se revisa antes que las palabras clave de otros.
            version = f"15.{luraph_header.group(2) or '0'}"
            evidence = f"encabezado «Luraph Obfuscator v{version}»"
            if (luraph_header.group(2) or "0") == "0":
                return "Luraph v15", "luraph15", evidence
            return "Luraph v15.1", "luraph151", evidence
        if "moonsec" in code_lower:
            return "MoonSec (V2 / variante no soportada)", None, "aparece «moonsec» pero no el banner de V3"
        if "goofyscator" in code_lower:
            return "Goofyscator (variante no soportada)", None, "aparece «goofyscator» pero no el banner de V11 BETA-1"
        if head.startswith("return setmetatable({") and (
                LURAPH15_SHAPE.search(head[:2000]) or "LPH" in code[:200000]):
            # Encabezado borrado: la forma de la VM de Luraph v15.
            return "Luraph v15 (sin encabezado)", "luraph15", "estructura de la VM de Luraph v15"
        prom = [kw for kw in ("prometheus", "levno", "prm_", "pdeobf") if kw in code_lower]
        if prom:
            return "Prometheus Obfuscator", "prometheus", "firmas: " + ", ".join(prom)
        lura = [kw for kw in ("lph_", "luraph", "lura.ph", "devirtualizing") if kw in code_lower]
        if lura:
            if "v15.1" in code_lower or "path2d" in code or "15.1" in code_lower:
                return "Luraph v15.1 (Avanzado)", "luraph151", "firmas: " + ", ".join(lura) + " + v15.1"
            return "Luraph (Variante Personalizada)", "luraph151", "firmas: " + ", ".join(lura)
        return "No compatible / Ofuscador Desconocido", None, "sin firmas conocidas"

    @staticmethod
    def detect_version(code: str) -> str:
        return LuauOptimizer.identify(code)[0]

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
# Discord muestra el color 0x000000 como "sin color"; 0x010101 pinta la franja realmente negra.
EMBED_BLACK = discord.Color.from_rgb(1, 1, 1)

@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(
        title="Lexy Hub • Deobf",
        description="Usa el comando con un **archivo adjunto**, una **URL** o **respondiendo** a un mensaje con archivo.",
        color=EMBED_BLACK
    )
    embed.add_field(
        name="⚡ Universal",
        value="`.deobf` — prueba todos los desofuscadores hasta que uno funcione",
        inline=False
    )
    embed.add_field(
        name="🔓 Desofuscadores",
        value=(
            "`.luraph` — Luraph v15 / v15.1 (detecta la versión)\n"
            "`.prometheus` — Prometheus\n"
            "`.moonveil` — MoonSec V3\n"
            "`.goofy` — Goofyscator V11"
        ),
        inline=False
    )
    embed.add_field(
        name="🛠️ Herramientas",
        value=(
            "`.detect` — identifica el ofuscador\n"
            "`.beautify` — limpia e indenta el código\n"
            "`.get <URL>` — descarga el código en texto plano\n"
            "`.list` — desofuscadores disponibles"
        ),
        inline=False
    )
    embed.set_footer(text="Lexy Hub Security")
    await ctx.send(embed=embed)

# ==================== COMANDO: .LIST ====================
@bot.command(name="list")
async def cmd_list(ctx):
    embed = discord.Embed(
        description="Deobfs Availables:\nLuraph v15/v15.1\nPrometheus\nMoonSec V3\nGoofyscator",
        color=EMBED_BLACK
    )
    await ctx.send(embed=embed)

# ==================== COMANDO: .DETECT ====================
@bot.command(name="detect")
async def cmd_detect(ctx, url: str = None):
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Analizando...", description="Escaneando firmas de ofuscación...", color=discord.Color.blue()))
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        label, command_name, evidence = LuauOptimizer.identify(code)

        if command_name:
            embed_desc = (
                f"## {EMOJI_CORRECT} SIGNATURE DETECTED\n"
                f"**Ofuscador Identificado:**\n```ini\n[{label}]\n```\n"
                f"**Evidencia:** {evidence}\n"
                f"**Comando:** `.{command_name}` (o `.deobf`)\n"
                f"Source: {source_link}\n"
                f"-# size: {LuauOptimizer.format_size(input_size)}"
            )
            color = discord.Color.from_rgb(0, 204, 102)
        else:
            embed_desc = (
                f"## {EMOJI_ERROR} NO SIGNATURE MATCH\n"
                f"**Resultado:**\n```ini\n[{label}]\n```\n"
                f"**Evidencia:** {evidence}\n"
                f"Prueba `.deobf`: intenta con todos los desofuscadores.\n"
                f"Source: {source_link}\n"
                f"-# size: {LuauOptimizer.format_size(input_size)}"
            )
            color = discord.Color.red()
        await msg.edit(content=None, embed=discord.Embed(description=embed_desc, color=color))
    except Exception as e:
        logger.error(f"Error en .detect: {e}", exc_info=True)
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_ERROR} Error", description=str(e)[:200], color=discord.Color.red()))

# ==================== COMANDO: .GET ====================
@bot.command(name="get")
async def cmd_get(ctx, url: str = None):
    if not url:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_ERROR} Error", description="Proporciona una URL válida.", color=discord.Color.red()))
        return
    if not url.startswith(("http://", "https://")): url = "https://" + url

    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Conectando...", color=discord.Color.blue()))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as res:
                if res.status != 200:
                    await msg.edit(embed=discord.Embed(title=f"{EMOJI_ERROR} Error HTTP", color=discord.Color.red()))
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
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_ERROR} Error", description=str(e)[:200], color=discord.Color.red()))

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
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_ERROR} Error", description=str(e)[:200], color=discord.Color.red()))

# ==================== MOTORES (devuelven el código o lanzan DeobfError) ====================
class DeobfError(Exception):
    """La herramienta no pudo desofuscar el script (mensaje corto para el usuario)."""
    title = "Fallo"

class NotCompatible(DeobfError):
    title = "No compatible"

class MissingDependency(DeobfError):
    title = "Falta en el servidor"

async def run_stage(args, deadline: float, label: str, cwd: str = None, check: bool = True):
    """Ejecuta una etapa del pipeline respetando un presupuesto de tiempo compartido."""
    proc = await asyncio.create_subprocess_exec(
        *[str(a) for a in args],
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name != "nt")
    )
    remaining = deadline - asyncio.get_running_loop().time()
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), max(1, remaining))
    except asyncio.TimeoutError:
        try:
            if os.name == "nt": proc.kill()
            else: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.communicate()
        raise DeobfError(f"{label}: tiempo agotado")
    if check and proc.returncode:
        diag = (stderr or stdout).decode("utf-8", "replace").strip()
        raise DeobfError(f"{label} falló: {diag[-800:]}")  # la causa suele estar al final
    return stdout, stderr

def _same_text(a: str, b: str) -> bool:
    """True si dos códigos son iguales salvo espacios: la herramienta no desofuscó nada."""
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)

def _remove(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try: os.remove(p)
            except Exception: pass

async def engine_luraph151(code, uid, timeout, strict=True):
    tool = os.path.join("v15_tool_attempt_source", "v15_tool_attempt_source", "deob.js")
    node_bin = shutil.which("node") or shutil.which("nodejs")
    if not node_bin:
        raise MissingDependency("Node.js (`node`)")
    if not os.path.isfile(tool):
        raise MissingDependency(f"archivos de `{LURAPH_ZIP}` (¿está junto al bot?)")

    input_file = f"input_{uid}.lua"
    output_file = f"output_{uid}.lua"
    expected_path = os.path.join("output", input_file)
    json_path = None
    try:
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)
        deadline = asyncio.get_running_loop().time() + timeout
        stdout, _ = await run_stage([node_bin, tool, input_file, output_file], deadline, "Luraph v15.1", check=False)

        raw_out = stdout.decode("utf-8", "replace").strip()
        try:
            js = json.loads(raw_out[raw_out.find('{'):raw_out.rfind('}') + 1])
            if js.get("success"): json_path = js.get("output")
        except Exception:
            pass

        result_code = ""
        for candidate in (json_path, expected_path, output_file):
            if candidate and os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8", errors="ignore") as f:
                    result_code = f.read()
                break
        if not result_code.strip():
            raise DeobfError("El script contiene protecciones pesadas o no es Luraph v15.1.")
        if _same_text(result_code, code):
            raise DeobfError("La salida es idéntica a la entrada.")
        return LuauOptimizer.beautify(result_code)
    finally:
        _remove(input_file, output_file, json_path, expected_path)

async def engine_prometheus(code, uid, timeout, strict=True):
    tool = os.path.join("Prometheus-Deobfuscator-main", "bin", "pdeobf.js")
    node_bin = shutil.which("node") or shutil.which("nodejs")
    if not node_bin:
        raise MissingDependency("Node.js (`node`)")
    if not os.path.isfile(tool):
        raise MissingDependency(f"archivos de `{PROM_ZIP}` (¿está junto al bot?)")

    input_file = f"prom_input_{uid}.lua"
    output_file = f"prom_output_{uid}.lua"
    try:
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)
        deadline = asyncio.get_running_loop().time() + timeout
        stdout, stderr = await run_stage([node_bin, tool, input_file, output_file], deadline, "Prometheus", check=False)

        result_code = ""
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
                result_code = f.read()
        elif stdout.strip():
            result_code = stdout.decode("utf-8", "replace").strip()

        if not result_code.strip():
            detail = (stderr or stdout).decode("utf-8", "replace").strip() or "sin detalles"
            raise DeobfError(f"No se pudo desofuscar con Prometheus: {detail[:150]}")
        if _same_text(result_code, code):
            raise DeobfError("La salida es idéntica a la entrada.")
        return LuauOptimizer.beautify(result_code)
    finally:
        _remove(input_file, output_file)

async def engine_moonveil(code, uid, timeout, strict=True):
    if strict and not re.search(r"protected (?:with|using) MoonSec V3\b", code[:3000], re.I):
        raise NotCompatible("No se detectó el banner de **MoonSec V3** (MoonSec V2 no está soportado).")

    dotnet_bin = shutil.which("dotnet") or os.path.expanduser("~/.dotnet/dotnet")
    java_bin = os.getenv("MOONSEC_JAVA") or shutil.which("java")
    missing = []
    if not dotnet_bin or not os.path.exists(dotnet_bin): missing.append(".NET 9 runtime (`dotnet`)")
    if not java_bin: missing.append("Java 8+ (`java`)")
    if not os.path.isfile(MOON_DLL) or not os.path.isfile(MOON_JAR):
        missing.append(f"archivos de `{MOON_ZIP}` (¿está junto al bot?)")
    if missing:
        raise MissingDependency(", ".join(missing))

    work_dir = tempfile.mkdtemp(prefix=f"moon_{uid}_")
    try:
        input_file = os.path.join(work_dir, "input.lua")
        bytecode_file = os.path.join(work_dir, "recovered.luac")
        output_file = os.path.join(work_dir, "deobfuscated.lua")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        deadline = asyncio.get_running_loop().time() + timeout
        # Etapa 1: MoonSec V3 -> bytecode Lua 5.1
        await run_stage([dotnet_bin, MOON_DLL, "-dev", "-i", input_file, "-o", bytecode_file], deadline, "MoonSec")
        if not os.path.isfile(bytecode_file):
            raise DeobfError("MoonSec no generó bytecode.")
        with open(bytecode_file, "rb") as f:
            if f.read(5) != b"\x1bLua\x51":
                raise DeobfError("MoonSec no generó bytecode Lua 5.1 válido.")

        # Etapa 2: bytecode -> código fuente con unluac
        await run_stage([java_bin, "-Xmx512m", "-jar", MOON_JAR, "--nodebug", "-o", output_file, bytecode_file], deadline, "unluac")
        if not os.path.isfile(output_file):
            raise DeobfError("unluac no generó salida.")
        with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        if not result_code.strip():
            raise DeobfError("unluac produjo una salida vacía.")
        return LuauOptimizer.beautify(result_code)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

def resolve_tsx():
    """tsx local (engines/obf/node_modules), global, o npx como último recurso."""
    node_bin = shutil.which("node") or shutil.which("nodejs")
    local = os.path.join(GOOFY_ENGINES, "obf", "node_modules", "tsx", "dist", "cli.mjs")
    if node_bin and os.path.isfile(local):
        return [node_bin, os.path.abspath(local)]
    if shutil.which("tsx"):
        return [shutil.which("tsx")]
    if shutil.which("npx"):
        return [shutil.which("npx"), "--yes", "tsx"]
    return None

async def engine_goofy(code, uid, timeout, strict=True):
    if len(code.encode("utf-8")) > 5_000_000:
        raise NotCompatible("Goofyscator acepta hasta 5 MB.")
    if not GOOFY_BANNER.search(code.lstrip("\ufeff \t\r\n")[:3000]):
        raise NotCompatible("No se detectó el banner de **Goofyscator V11 BETA-1**.")

    tsx_cmd = resolve_tsx()
    missing = []
    if not os.path.isfile(os.path.join(GOOFY_ENGINES, "goofyscator", "cli.mjs")):
        missing.append(f"archivos de `{GOOFY_ZIP}` (¿está junto al bot?)")
    if not tsx_cmd:
        missing.append("Node.js + `tsx`")
    for exe in ("luau", "luau-ast"):
        if not os.path.isfile(os.path.join(GOOFY_BIN, exe)):
            missing.append(f"binario Linux `{exe}` en `{GOOFY_BIN}/`")
    if missing:
        raise MissingDependency(", ".join(missing))

    work_dir = tempfile.mkdtemp(prefix=f"goofy_{uid}_")
    try:
        input_file = os.path.join(work_dir, "input.lua")
        analysis_file = os.path.join(work_dir, "goofyscator-v11-analysis.json")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        deadline = asyncio.get_running_loop().time() + timeout
        cli = os.path.abspath(os.path.join(GOOFY_ENGINES, "goofyscator", "cli.mjs"))
        # cwd = engines/ porque capture.mjs resuelve "deobfuscator/deobf/bin/luau" relativo al cwd.
        stdout, stderr = await run_stage(
            tsx_cmd + [cli, os.path.abspath(input_file), os.path.abspath(analysis_file)],
            deadline, "Goofyscator", cwd=GOOFY_ENGINES, check=False
        )
        try:
            summary = json.loads(stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise DeobfError("Goofyscator no devolvió resultado: " + stderr.decode("utf-8", "replace")[-300:])
        if not summary.get("ok"):
            raise DeobfError("Goofyscator V11 falló: " + str(summary.get("error", "sin detalles"))[:300])
        if summary.get("artifact_only"):
            # Solo reporte de diagnóstico: no es Lua desofuscado.
            raise DeobfError("Recuperación incompleta: " + str(summary.get("status", ""))[:300])

        result_file = os.path.join(work_dir, "deobfuscated.lua")
        if not os.path.isfile(result_file):
            raise DeobfError("Goofyscator no generó deobfuscated.lua")
        with open(result_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        if not result_code.strip():
            raise DeobfError("Goofyscator produjo una salida vacía.")
        # El motor ya valida y formatea su salida con Luau: no se pasa por .beautify.
        return result_code.strip()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

async def engine_luraph15(code, uid, timeout, strict=True):
    missing = []
    if not os.path.isfile(LURAPH15_SCRIPT):
        missing.append(f"archivos de `{LURAPH15_ZIP}` (¿está junto al bot?)")
    for exe in ("luau", "luau-ast"):
        if not os.path.isfile(os.path.join(LURAPH15_BIN, exe)):
            missing.append(f"binario Linux `{exe}` en `{LURAPH15_BIN}/`")
    if missing:
        raise MissingDependency(", ".join(missing))

    work_dir = tempfile.mkdtemp(prefix=f"lph15_{uid}_")
    try:
        input_file = os.path.join(work_dir, "input.lua")
        output_file = os.path.join(work_dir, "output.lua")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        deadline = asyncio.get_running_loop().time() + timeout
        # Un subproceso por archivo (el módulo guarda estado global). cwd = carpeta del proyecto.
        await run_stage(
            [sys.executable, os.path.abspath(LURAPH15_SCRIPT), input_file, "-o", output_file, "--obfuscator", "luraph_v15"],
            deadline, "Luraph v15", cwd=LURAPH15_DIR
        )
        if not os.path.isfile(output_file):
            raise DeobfError("El desofuscador no generó resultado.")
        with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        if not result_code.strip():
            raise DeobfError("El desofuscador produjo una salida vacía.")
        # La salida ya viene formateada por el lifter (y con el crédito de la herramienta).
        return result_code.strip()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

ENGINES = {
    "luraph15": {
        "label": "Luraph v15", "fn": engine_luraph15, "title": "LURAPH V15 DEOBFUSCATED",
        "loading": ("Desofuscando Luraph v15...", "Devirtualizando la VM (puede tardar)...", discord.Color.from_rgb(0, 128, 255)),
    },
    "luraph151": {
        "label": "Luraph v15.1", "fn": engine_luraph151, "title": "LURAPH V15.1 DEOBFUSCATED",
        "loading": ("Desofuscando Luraph v15.1...", "Procesando capas de virtualización...", discord.Color.from_rgb(0, 128, 255)),
    },
    "prometheus": {
        "label": "Prometheus", "fn": engine_prometheus, "title": "PROMETHEUS DEOBFUSCATED",
        "loading": ("Desofuscando Prometheus...", "Procesando desofuscación...", discord.Color.from_rgb(0, 204, 102)),
    },
    "moonveil": {
        "label": "MoonSec V3", "fn": engine_moonveil, "title": "MOONSEC V3 DEOBFUSCATED",
        "loading": ("Desofuscando MoonSec V3...", "Devirtualizando bytecode...", discord.Color.from_rgb(120, 80, 255)),
    },
    "goofy": {
        "label": "Goofyscator", "fn": engine_goofy, "title": "GOOFYSCATOR V11 DEOBFUSCATED",
        "loading": ("Desofuscando Goofyscator...", "Recuperando la VM V11...", discord.Color.from_rgb(255, 170, 0)),
    },
}
# Orden de prueba de .deobf (primero va el detectado). El de Luraph v15 va al final: es el más lento.
DEOBF_ORDER = ["luraph151", "prometheus", "moonveil", "goofy", "luraph15"]
DEOBF_PER_ENGINE_TIMEOUT = 120
DEOBF_TOTAL_TIMEOUT = 420

async def deliver_result(ctx, msg, title, result_code, source_link, input_size, start_time):
    """Envía el embed con la vista previa y el archivo (mismo formato en todos los desofuscadores)."""
    final_text = f"-- Deobfuscado por Lexy Deobf\n\n{result_code}\n"
    path = f"executable_script_{ctx.message.id}.lua"
    try:
        with open(path, "w", encoding="utf-8") as f: f.write(final_text)
        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time

        preview_lines = final_text.splitlines()[:8]
        preview = "\n".join(preview_lines)
        if len(final_text.splitlines()) > 8: preview += "\n--"

        embed_desc = (
            f"## {EMOJI_CORRECT} {title}\n"
            f"**Output Preview**\n"
            f"```lua\n{preview}\n```\n"
            f"Source: {source_link}\n"
            f"-# input: {LuauOptimizer.format_size(input_size)} · output: {LuauOptimizer.format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            f"**Output File:**"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))

        await msg.delete()
        # Embed primero y el archivo en un mensaje separado abajo
        await ctx.send(embed=embed)
        await ctx.send(file=discord.File(path, filename="executable_script.lua"))
    finally:
        _remove(path)

async def run_engine_command(ctx, url, key):
    """Flujo de un comando directo (.luraph15, .prometheus, ...)."""
    spec = ENGINES[key]
    start_time = time.time()
    title, desc, color = spec["loading"]
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} {title}", description=desc, color=color))
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        result = await spec["fn"](code, str(ctx.message.id), 300, True)
        await deliver_result(ctx, msg, spec["title"], result, source_link, input_size, start_time)
    except DeobfError as e:
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_ERROR} {e.title}", description=str(e)[:600], color=discord.Color.red()))
    except Exception as e:
        logger.error(f"Error crítico en .{key}: {e}", exc_info=True)
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_ERROR} Error Crítico", description=f"```{str(e)[:400]}```", color=discord.Color.red()))

# ==================== COMANDOS DE DESOFUSCADORES ====================
@bot.command(name="luraph15")
async def cmd_luraph15(ctx, url: str = None):
    await run_engine_command(ctx, url, "luraph15")

@bot.command(name="luraph151")
async def cmd_luraph151(ctx, url: str = None):
    await run_engine_command(ctx, url, "luraph151")

@bot.command(name="prometheus")
async def cmd_prometheus(ctx, url: str = None):
    await run_engine_command(ctx, url, "prometheus")

@bot.command(name="moonveil", aliases=["moonsec", "msd"])
async def cmd_moonveil(ctx, url: str = None):
    await run_engine_command(ctx, url, "moonveil")

@bot.command(name="goofy", aliases=["goofyscator", "gv11d"])
async def cmd_goofy(ctx, url: str = None):
    await run_engine_command(ctx, url, "goofy")

# ==================== COMANDO: .LURAPH (auto v15 / v15.1) ====================
@bot.command(name="luraph")
async def cmd_luraph(ctx, url: str = None):
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
    except Exception as e:
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_ERROR} Error", description=str(e)[:200], color=discord.Color.red()))
        return

    label, command_name, _ = LuauOptimizer.identify(code)
    if command_name in ("luraph15", "luraph151"):
        target = command_name
    elif command_name is not None or not label.startswith("No compatible"):
        # Reconocido como otro ofuscador (o uno sin soporte, p. ej. MoonSec V2): no es Luraph.
        hint = f"Usa `.{command_name}` o `.deobf`." if command_name else "Prueba con `.deobf`."
        await ctx.send(embed=discord.Embed(title=f"{EMOJI_ERROR} No es Luraph", description=f"Detectado: **{label}**. {hint}", color=discord.Color.red()))
        return
    else:
        target = "luraph151"   # sin firma clara: se mantiene el comportamiento anterior (motor v15.1)

    ctx._lexy_cache = (code, source_link, input_size)   # evita descargar dos veces
    await run_engine_command(ctx, url, target)

# ==================== COMANDO: .DEOBF (UNIVERSAL: prueba todos) ====================
@bot.command(name="deobf")
async def cmd_deobf(ctx, url: str = None):
    start_time = time.time()
    msg = await ctx.send(embed=discord.Embed(title=f"{EMOJI_LOADING} Analizando...", description="Leyendo el script...", color=discord.Color.blue()))
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
    except Exception as e:
        await msg.edit(embed=discord.Embed(title=f"{EMOJI_ERROR} Error", description=str(e)[:200], color=discord.Color.red()))
        return

    label, detected, _ = LuauOptimizer.identify(code)
    order = ([detected] if detected in ENGINES else []) + [k for k in DEOBF_ORDER if k != detected]
    logger.info(f".deobf: detectado '{label}' -> orden {order}")

    uid = str(ctx.message.id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEOBF_TOTAL_TIMEOUT
    failures = []

    for i, key in enumerate(order, 1):
        spec = ENGINES[key]
        remaining = deadline - loop.time()
        if remaining < 10:
            failures.append((spec["label"], "sin tiempo restante"))
            continue
        await msg.edit(embed=discord.Embed(
            title=f"{EMOJI_LOADING} Probando {spec['label']}... ({i}/{len(order)})",
            description=f"Detectado: **{label}**",
            color=spec["loading"][2]
        ))
        try:
            result = await spec["fn"](code, uid, min(remaining, DEOBF_PER_ENGINE_TIMEOUT), False)
            await deliver_result(ctx, msg, spec["title"], result, source_link, input_size, start_time)
            return
        except DeobfError as e:
            failures.append((spec["label"], str(e)))
        except Exception as e:
            logger.error(f".deobf: {spec['label']} lanzó {e}", exc_info=True)
            failures.append((spec["label"], f"error interno: {str(e)[:80]}"))

    lines = "\n".join(f"• **{name}:** {reason.replace(chr(10), ' ')[:110]}" for name, reason in failures)
    await msg.edit(embed=discord.Embed(
        title=f"{EMOJI_ERROR} No se pudo desofuscar",
        description=f"Detectado: `{label}`\nSe probaron todos los desofuscadores:\n{lines}",
        color=discord.Color.red()
    ))

# ==================== INICIO DEL BOT ====================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    logger.critical("¡Falta la variable de entorno DISCORD_TOKEN!")
else:
    bot.run(TOKEN)
