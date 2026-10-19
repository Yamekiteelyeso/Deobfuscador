import os
import sys
import zipfile
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
import subprocess
from collections import deque
from dataclasses import dataclass, field
from discord.ext import commands

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LexyHubBot")

# ==================== EMOJIS ====================
EMOJI_LOADING = "<a:loading:1561435149793493166>"
EMOJI_CORRECT = "<:correct:1561510204393136209>"
EMOJI_ERROR = "<:error:1561510204393136209>"
EMOJI_LIST = "<:list:1561778149514149888>"
EMOJI_LURAPH = "<:luraph:1561779566635126845>"
EMOJI_PROMETHEUS = "<:prometheus:1561782588022984774>"

# ==================== CONFIGURACIÓN ====================
def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default

MAX_CONCURRENT_JOBS = max(1, _env_int("MAX_CONCURRENT_JOBS", 2))
MAX_WAITING_JOBS = max(1, _env_int("MAX_WAITING_JOBS", 15))
MAX_INPUT_BYTES = _env_int("MAX_INPUT_MB", 8) * 1024 * 1024
HARD_JOB_TIMEOUT = 720

# ==================== HERRAMIENTAS Y ZIPS ====================
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

GOOFY_ZIP = "goofyscator-deobf.zip"
GOOFY_DIR = "goofyscator-deobf"
GOOFY_ENGINES = os.path.join(GOOFY_DIR, "engines")
GOOFY_BANNER = re.compile(r"^--[^\n]*protected by goofyscator V11 BETA-1\b", re.I)


def extract_zip(zip_path, marker_dir, target="."):
    if os.path.exists(zip_path) and not os.path.exists(marker_dir):
        logger.info(f"Descomprimiendo {zip_path}...")
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(target)
            logger.info(f"{zip_path} descomprimido con éxito.")
        except Exception as e:
            logger.error(f"Error al descomprimir {zip_path}: {e}")


def find_file_recursively(filename):
    for root, dirs, files in os.walk("."):
        if filename in files:
            return os.path.join(root, filename)
    return None


def make_all_binaries_executable():
    binarios_necesarios = {"luau", "luau-ast"}
    for root, dirs, files in os.walk("."):
        for file in files:
            if file in binarios_necesarios:
                p = os.path.join(root, file)
                try:
                    os.chmod(p, 0o755)
                except Exception:
                    pass


# 1. Descomprimir todas las herramientas una sola vez
extract_zip(LURAPH_ZIP, LURAPH_DIR, LURAPH_DIR)
extract_zip(PROM_ZIP, PROM_DIR)
extract_zip(MOON_ZIP, MOON_DIR)
extract_zip(GOOFY_ZIP, GOOFY_ENGINES, GOOFY_DIR)

if os.path.exists(LURAPH15_ZIP) and not os.path.exists(LURAPH15_DIR):
    logger.info(f"Descomprimiendo {LURAPH15_ZIP}...")
    try:
        os.makedirs(LURAPH15_DIR, exist_ok=True)
        with zipfile.ZipFile(LURAPH15_ZIP, "r") as z:
            z.extractall(LURAPH15_DIR)
        logger.info(f"{LURAPH15_ZIP} descomprimido con éxito.")
    except Exception as e:
        logger.error(f"Error al descomprimir {LURAPH15_ZIP}: {e}")

# 2. Verificar si ya existen los binarios compilados de Luau; si no, ejecutar build_luau.py una sola vez
bin_luau_exists = find_file_recursively("luau")
bin_luau_ast_exists = find_file_recursively("luau-ast")

if not (bin_luau_exists and bin_luau_ast_exists):
    build_script = find_file_recursively("build_luau.py")
    if build_script:
        logger.info(f"Binarios no encontrados. Ejecutando {build_script}...")
        try:
            subprocess.run([sys.executable, os.path.basename(build_script)], cwd=os.path.dirname(build_script), check=False)
        except Exception as e:
            logger.warning(f"Aviso al ejecutar script de compilación: {e}")

# 3. Aplicar permisos de ejecución a los binarios
make_all_binaries_executable()

if os.path.isdir(GOOFY_ENGINES):
    try:
        _pkg = os.path.join(GOOFY_ENGINES, "package.json")
        if not os.path.exists(_pkg):
            with open(_pkg, "w", encoding="utf-8") as _f:
                _f.write('{"type":"module"}\n')
    except Exception as e:
        logger.error(f"Error preparando Goofyscator: {e}")

# ==================== BOT SETUP ====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

EMBED_BLACK = discord.Color.from_rgb(1, 1, 1)


@bot.event
async def on_ready():
    logger.info(f"¡Bot conectado exitosamente como {bot.user}!")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="scripts Luau | .help")
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Error en comando {getattr(ctx.command, 'name', '?')}: {error}")


# ==================== UTILIDADES UI ====================
def _desc(emoji, head, body=""):
    text = f"# {emoji} {head}"
    if body:
        text += f"\n{body}"
    return text[:4000]


def ui_loading(head, body=""):
    return discord.Embed(description=_desc(EMOJI_LOADING, head, body), color=discord.Color.blue())


def ui_error(head, body=""):
    return discord.Embed(description=_desc(EMOJI_ERROR, head, body), color=discord.Color.red())


def ui_ok(head, body=""):
    return discord.Embed(description=_desc(EMOJI_CORRECT, head, body), color=discord.Color.from_rgb(0, 204, 102))


async def safe_edit(msg, embed):
    try:
        await msg.edit(content=None, embed=embed)
    except Exception as e:
        logger.warning(f"No se pudo editar el mensaje: {e}")


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def make_preview(text, max_lines=8, max_line_len=110, max_total=900):
    lines = text.splitlines()
    out = []
    for line in lines[:max_lines]:
        out.append(line if len(line) <= max_line_len else line[:max_line_len] + " ...")
    preview = "\n".join(out)
    if len(preview) > max_total:
        preview = preview[:max_total] + " ..."
    if len(lines) > max_lines:
        preview += "\n--"
    return preview.replace("```", "'''")


# ==================== OBTENCIÓN DE CÓDIGO ====================
async def get_code_and_source(ctx, url=None):
    async def from_attachment(att):
        if att.size > MAX_INPUT_BYTES:
            raise Exception(f"El archivo pesa {format_size(att.size)} y el máximo es {format_size(MAX_INPUT_BYTES)}.")
        data = await att.read()
        return data.decode("utf-8-sig", errors="ignore"), att.url, att.size

    if ctx.message.attachments:
        return await from_attachment(ctx.message.attachments[0])

    if ctx.message.reference and ctx.message.reference.message_id:
        try:
            ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if ref_msg.attachments:
                return await from_attachment(ref_msg.attachments[0])
        except Exception as e:
            if "pesa" in str(e):
                raise
            logger.warning(f"No se pudo leer el mensaje respondido: {e}")

    if url:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    raise Exception(f"Error HTTP al acceder a la URL: {res.status}")
                data = await res.content.read(MAX_INPUT_BYTES + 1)
                if len(data) > MAX_INPUT_BYTES:
                    raise Exception(f"El archivo supera el máximo de {format_size(MAX_INPUT_BYTES)}.")
        return data.decode("utf-8-sig", errors="ignore"), url, len(data)

    raise Exception("No encontré un archivo adjunto, un mensaje respondido con archivo ni una URL válida.")


# ==================== DETECTOR DE OFUSCADORES ====================
@dataclass
class Finding:
    family: str
    label: str
    score: float
    evidence: list = field(default_factory=list)
    hint: str = ""


CONFIDENT = 0.5

class Detector:
    @staticmethod
    def scan(code):
        s = code[:500000]
        findings = []

        # 1. Goofyscator V11
        goofy_score = 0.0
        goofy_ev = []
        if "-- protected by goofyscator" in s.lower() or "limitedstack" in s:
            goofy_score = 0.95
            goofy_ev.append("Firma o string interno de Goofyscator V11")
        findings.append(Finding("goofy", "Goofyscator V11", goofy_score, goofy_ev))

        # 2. Prometheus
        prom_score = 0.0
        prom_ev = []
        if "prometheus" in s.lower() or "levno" in s.lower():
            prom_score = 0.95
            prom_ev.append("Marca de agua de Prometheus")
        findings.append(Finding("prometheus", "Prometheus", prom_score, prom_ev))

        # 3. MoonSec V3
        moon_score = 0.0
        moon_ev = []
        if re.search(r'[\"\']\\4\\8', s) or re.search(r'\(?["\'](?:\\\d{1,3}){10,}', s):
            moon_score = 0.90
            moon_ev.append("Constantes cifradas de MoonSec V3 (\\4\\8)")
        findings.append(Finding("moonsec", "MoonSec V3", moon_score, moon_ev))

        # 4. Luraph v15 / v15.1
        lur_score = 0.0
        lur_ev = []
        lur_hint = ""
        
        if re.search(r"Luraph Obfuscator", s, re.I):
            lur_score += 0.80
            lur_ev.append("Encabezado explícito de Luraph Obfuscator")
        
        tree_matches = len(re.findall(r"\b[A-Za-z_]\w*\s*<=\s*\d+\s+then\s+if\s+[A-Za-z_]\w*\s*<=\s*\d+\s+then", s))
        if tree_matches >= 6:
            lur_score += 0.40
            lur_ev.append(f"Árbol de despacho binario complejo de Luraph ({tree_matches} niveles)")

        lur_score = min(lur_score, 1.0)
        m = re.search(r"Luraph Obfuscator v(\d+)\.(\d+)", s, re.I)
        if m:
            lur_hint = f"{m.group(1)}.{m.group(2)}"
        
        label = "Luraph v15"
        if lur_hint == "15.1":
            label = "Luraph v15.1"
        elif lur_hint.startswith("15"):
            label = "Luraph v15"
        findings.append(Finding("luraph", label, lur_score, lur_ev, lur_hint))

        # 5. IronBrew 1
        ib_score = 0.0
        ib_ev = []
        if re.search(r"\breturn\s*\(\s*function\s*\(\s*(?:[A-Za-z_]\w*\s*,\s*){15,}", s):
            ib_score = 0.90
            ib_ev.append("Función envoltorio con más de 15 parámetros (IronBrew)")
        findings.append(Finding("ironbrew", "IronBrew 1", ib_score, ib_ev))

        findings.sort(key=lambda f: f.score, reverse=True)
        return findings


# ==================== OPTIMIZADOR / BEAUTIFIER ====================
class LuauOptimizer:
    @staticmethod
    def deep_clean_and_fix(code):
        fixed_code = code.replace("if nil == 1 then", "if 1 == 1 then").replace("elseif nil == 2 then", "elseif 1 == 2 then")
        fixed_code = re.sub(r'local function\s+fn\d+\s*\(\s*\)\s*end', '-- [Función vacía removida]', fixed_code)
        cleaned = []
        for line in fixed_code.splitlines():
            if "devirt:" in line or 'error("devirt:' in line or "LPH:" in line or "Prometheus" in line:
                continue
            if line.strip().startswith("--[[") and "corrupted" in line.lower():
                continue
            cleaned.append(line)
        result = "\n".join(cleaned)
        result = re.sub(r'\n\s*\n\s*\n+', '\n\n', result)
        return result.strip()

    @staticmethod
    def beautify(code):
        optimized = LuauOptimizer.deep_clean_and_fix(code)
        formatted = []
        indent = 0
        tab = "    "
        decrease_kw = {"end", "until", "else", "elseif"}
        increase_kw = {"do", "then", "repeat", "function"}
        starters = {"if", "for", "while", "local function", "function", "repeat"}

        for line in optimized.splitlines():
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


# ==================== MOTORES DE DESOFUSCACIÓN ====================
class DeobfError(Exception):
    head = "Fallo"


class MissingDependency(DeobfError):
    head = "Falta en el servidor"


async def run_stage(args, deadline, label, cwd=None, check=True):
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
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.communicate()
        raise DeobfError(f"{label}: tiempo agotado")
    if check and proc.returncode:
        diag = (stderr or stdout).decode("utf-8", "replace").strip()
        raise DeobfError(f"{label} falló: {diag[-600:]}")
    return stdout, stderr


def _same_text(a, b):
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def _remove(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def _node():
    return shutil.which("node") or shutil.which("nodejs")


async def engine_luraph151(code, uid, timeout):
    tool = find_file_recursively("deob.js")
    node_bin = _node()
    if not node_bin:
        raise MissingDependency("Node.js (`node`)")
    if not tool:
        raise MissingDependency(f"archivos de `{LURAPH_ZIP}`")

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
            js = json.loads(raw_out[raw_out.find("{"):raw_out.rfind("}") + 1])
            if js.get("success"):
                json_path = js.get("output")
        except Exception:
            pass

        result_code = ""
        for candidate in (json_path, expected_path, output_file):
            if candidate and os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8", errors="ignore") as f:
                    result_code = f.read()
                break
        if not result_code.strip():
            raise DeobfError("El motor no produjo salida.")
        return LuauOptimizer.beautify(result_code)
    finally:
        _remove(input_file, output_file, json_path, expected_path)


async def engine_prometheus(code, uid, timeout):
    tool = find_file_recursively("pdeobf.js")
    node_bin = _node()
    if not node_bin:
        raise MissingDependency("Node.js (`node`)")
    if not tool:
        raise MissingDependency(f"archivos de `{PROM_ZIP}`")

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
            raise DeobfError(f"El motor no produjo salida: {detail[-200:]}")
        return LuauOptimizer.beautify(result_code)
    finally:
        _remove(input_file, output_file)


async def engine_moonsec(code, uid, timeout):
    dotnet_bin = shutil.which("dotnet") or os.path.expanduser("~/.dotnet/dotnet")
    java_bin = os.getenv("MOONSEC_JAVA") or shutil.which("java")
    missing = []
    if not dotnet_bin or not os.path.exists(dotnet_bin):
        missing.append(".NET 9 runtime (`dotnet`)")
    if not java_bin:
        missing.append("Java 8+ (`java`)")
    if not os.path.isfile(MOON_DLL) or not os.path.isfile(MOON_JAR):
        missing.append(f"archivos de `{MOON_ZIP}`")
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
        await run_stage([dotnet_bin, MOON_DLL, "-dev", "-i", input_file, "-o", bytecode_file], deadline, "MoonSec")
        if not os.path.isfile(bytecode_file):
            raise DeobfError("MoonSec no generó bytecode.")
        with open(bytecode_file, "rb") as f:
            if f.read(5) != b"\x1bLua\x51":
                raise DeobfError("MoonSec no generó bytecode Lua 5.1 válido.")

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
    node_bin = _node()
    local = os.path.join(GOOFY_ENGINES, "obf", "node_modules", "tsx", "dist", "cli.mjs")
    if node_bin and os.path.isfile(local):
        return [node_bin, os.path.abspath(local)]
    if shutil.which("tsx"):
        return [shutil.which("tsx")]
    if shutil.which("npx"):
        return [shutil.which("npx"), "--yes", "tsx"]
    return None


async def engine_goofy(code, uid, timeout):
    if len(code.encode("utf-8", "ignore")) > 5_000_000:
        raise DeobfError("Goofyscator acepta hasta 5 MB.")

    tsx_cmd = resolve_tsx()
    missing = []
    if not find_file_recursively("cli.mjs"):
        missing.append(f"archivos de `{GOOFY_ZIP}`")
    if not tsx_cmd:
        missing.append("Node.js + `tsx`")
    
    bin_found = any(os.path.isfile(os.path.join(root, exe)) for root, dirs, files in os.walk(".") for exe in ("luau", "luau-ast") if exe in files)
    if not bin_found:
        missing.append("binarios Linux `luau` / `luau-ast`")

    if missing:
        raise MissingDependency(", ".join(missing))

    if not GOOFY_BANNER.search(code.lstrip("\ufeff \t\r\n")[:3000]):
        code = "-- protected by goofyscator V11 BETA-1\n" + code

    work_dir = tempfile.mkdtemp(prefix=f"goofy_{uid}_")
    try:
        input_file = os.path.join(work_dir, "input.lua")
        analysis_file = os.path.join(work_dir, "goofyscator-v11-analysis.json")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        deadline = asyncio.get_running_loop().time() + timeout
        cli = find_file_recursively("cli.mjs")
        stdout, stderr = await run_stage(
            tsx_cmd + [os.path.abspath(cli), os.path.abspath(input_file), os.path.abspath(analysis_file)],
            deadline, "Goofyscator", cwd=GOOFY_ENGINES, check=False
        )
        try:
            summary = json.loads(stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise DeobfError("Goofyscator no devolvió resultado: " + stderr.decode("utf-8", "replace")[-250:])
        if not summary.get("ok"):
            raise DeobfError("Goofyscator V11 falló: " + str(summary.get("error", "sin detalles"))[:250])

        result_file = os.path.join(work_dir, "deobfuscated.lua")
        if not os.path.isfile(result_file):
            raise DeobfError("Goofyscator no generó deobfuscated.lua")
        with open(result_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        return result_code.strip()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def engine_luraph15(code, uid, timeout):
    missing = []
    script_path = find_file_recursively("deob.py")
    if not script_path:
        missing.append(f"archivos de `{LURAPH15_ZIP}`")
    
    bin_found = any(os.path.isfile(os.path.join(root, exe)) for root, dirs, files in os.walk(".") for exe in ("luau", "luau-ast") if exe in files)
    if not bin_found:
        missing.append("binarios Linux `luau` / `luau-ast`")

    if missing:
        raise MissingDependency(", ".join(missing))

    work_dir = tempfile.mkdtemp(prefix=f"lph15_{uid}_")
    try:
        input_file = os.path.join(work_dir, "input.lua")
        output_file = os.path.join(work_dir, "output.lua")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        deadline = asyncio.get_running_loop().time() + timeout
        await run_stage(
            [sys.executable, os.path.abspath(script_path), input_file, "-o", output_file, "--obfuscator", "luraph_v15"],
            deadline, "Luraph v15", cwd=os.path.dirname(script_path)
        )
        if not os.path.isfile(output_file):
            raise DeobfError("El desofuscador no generó resultado.")
        with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        return result_code.strip()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


ENGINES = {
    "luraph15":   {"label": "Luraph v15",   "family": "luraph",     "fn": engine_luraph15,   "title": "LURAPH V15 DEOBFUSCATED", "wait": "Devirtualizando Luraph v15..."},
    "luraph151":  {"label": "Luraph v15.1", "family": "luraph",     "fn": engine_luraph151,  "title": "LURAPH V15.1 DEOBFUSCATED", "wait": "Procesando Luraph v15.1..."},
    "prometheus": {"label": "Prometheus",   "family": "prometheus", "fn": engine_prometheus, "title": "PROMETHEUS DEOBFUSCATED", "wait": "Desofuscando Prometheus..."},
    "moonsec":    {"label": "MoonSec V3",   "family": "moonsec",    "fn": engine_moonsec,    "title": "MOONSEC V3 DEOBFUSCATED", "wait": "Devirtualizando MoonSec V3..."},
    "goofy":      {"label": "Goofyscator",  "family": "goofy",      "fn": engine_goofy,      "title": "GOOFYSCATOR V11 DEOBFUSCATED", "wait": "Recuperando Goofyscator V11..."},
}

FAMILY_ENGINES = {
    "luraph": ["luraph15", "luraph151"],
    "prometheus": ["prometheus"],
    "moonsec": ["moonsec"],
    "goofy": ["goofy"],
}


def engines_for(finding):
    keys = list(FAMILY_ENGINES.get(finding.family, []))
    if finding.family == "luraph" and finding.hint == "15.1":
        keys.reverse()
    return keys


def validate_result(original, result, family):
    if not result or not result.strip():
        return False, "salida vacía"
    if _same_text(result, original):
        return False, "la salida es idéntica a la entrada"
    head = result[:20000]
    bad = sum(1 for ch in head if ch not in "\r\n\t" and (ord(ch) < 32 or ord(ch) == 127))
    if head and bad / len(head) > 0.05:
        return False, "la salida es binaria"
    if not re.search(r"\b(local|function|end|return|print|if|for|while)\b", result):
        return False, "la salida no parece Lua"
    return True, ""


async def deliver_result(ctx, msg, title, result_code, source_link, input_size, start_time):
    final_text = f"-- Deobfuscado por Lexy Deobf\n\n{result_code}\n"
    path = f"executable_script_{ctx.message.id}.lua"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(final_text)
        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time
        body = (
            f"**Output Preview**\n"
            f"```lua\n{make_preview(final_text)}\n```\n"
            f"Source: {source_link}\n"
            f"-# input: {format_size(input_size)} · output: {format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            f"**Output File:**"
        )
        try:
            await msg.delete()
        except Exception:
            pass
        await ctx.send(embed=ui_ok(title, body))
        await ctx.send(file=discord.File(path, filename="executable_script.lua"))
    finally:
        _remove(path)


# ==================== COLA DE TRABAJOS ====================
class QueueRefused(Exception):
    pass


@dataclass(eq=False)
class Job:
    user_id: int
    msg: object
    work: object
    last_pos: int = -1


class JobQueue:
    def __init__(self, workers, max_waiting):
        self.workers = workers
        self.max_waiting = max_waiting
        self._queue = None
        self._waiting = deque()
        self._running = set()
        self._tasks = []
        self._refresh_lock = None

    def _ensure_started(self):
        if self._tasks:
            return
        self._queue = asyncio.Queue()
        self._refresh_lock = asyncio.Lock()
        for _ in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker()))

    def user_busy(self, user_id):
        return any(j.user_id == user_id for j in self._waiting) or any(j.user_id == user_id for j in self._running)

    def check(self, user_id):
        if self.user_busy(user_id):
            return "Ya tienes un trabajo en cola o ejecutándose."
        if len(self._running) >= self.workers and len(self._waiting) >= self.max_waiting:
            return f"La cola está llena ({self.max_waiting} esperando)."
        return None

    def stats(self):
        total = len(self._running) + len(self._waiting)
        running = min(self.workers, total)
        return running, total - running

    def _idle(self):
        return max(0, self.workers - len(self._running))

    def position_if_added(self):
        pos = len(self._waiting) - self._idle() + 1
        return pos if pos > 0 else 0

    def submit(self, job):
        reason = self.check(job.user_id)
        if reason:
            raise QueueRefused(reason)
        self._ensure_started()
        self._waiting.append(job)
        self._queue.put_nowait(job)

    async def _worker(self):
        while True:
            job = await self._queue.get()
            try:
                if job not in self._waiting:
                    continue
                self._waiting.remove(job)
                self._running.add(job)
                asyncio.create_task(self._refresh_positions())
                try:
                    await asyncio.wait_for(job.work(), HARD_JOB_TIMEOUT)
                except asyncio.TimeoutError:
                    await safe_edit(job.msg, ui_error("Tiempo agotado", "El trabajo tardó demasiado."))
                except Exception as e:
                    logger.error(f"Trabajo falló: {e}", exc_info=True)
                    await safe_edit(job.msg, ui_error("Error Crítico", f"```{str(e)[:400]}```"))
                finally:
                    self._running.discard(job)
            finally:
                self._queue.task_done()

    async def _refresh_positions(self):
        async with self._refresh_lock:
            idle = self._idle()
            for i, job in enumerate(list(self._waiting)):
                pos = i - idle + 1
                if pos <= 0:
                    continue
                if job.last_pos != pos:
                    job.last_pos = pos
                    await safe_edit(job.msg, ui_waiting(pos, *self.stats()))
                    await asyncio.sleep(0.4)


queue = JobQueue(MAX_CONCURRENT_JOBS, MAX_WAITING_JOBS)


def ui_waiting(position, running, waiting):
    return ui_loading(
        f"En cola · #{position}",
        f"Hay **{running}** procesando y **{waiting}** esperando."
    )


async def execute_plan(ctx, msg, code, source_link, input_size, plan, detected_label, start_time):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 600
    uid = str(ctx.message.id)
    failures = []

    for i, key in enumerate(plan, 1):
        spec = ENGINES[key]
        remaining = deadline - loop.time()
        if remaining < 10:
            failures.append((spec["label"], "sin tiempo restante"))
            continue
        step = f" ({i}/{len(plan)})" if len(plan) > 1 else ""
        await safe_edit(msg, ui_loading(f"Desofuscando {spec['label']}{step}", f"{spec['wait']}\nDetectado: **{detected_label}**"))
        try:
            result = await spec["fn"](code, uid, min(remaining, 300))
            ok, why = await asyncio.to_thread(validate_result, code, result, spec["family"])
        except DeobfError as e:
            failures.append((spec["label"], str(e)))
            continue
        except Exception as e:
            logger.error(f"{spec['label']} lanzó {e}", exc_info=True)
            failures.append((spec["label"], f"error interno"))
            continue
        if not ok:
            failures.append((spec["label"], why))
            continue

        try:
            await deliver_result(ctx, msg, spec["title"], result, source_link, input_size, start_time)
        except Exception as e:
            logger.error(f"No se pudo enviar el resultado: {e}", exc_info=True)
        return

    lines = "\n".join(f"**{name}:** {reason}" for name, reason in failures)
    await safe_edit(msg, ui_error("No se pudo desofuscar", f"Detectado: **{detected_label}**\n{lines}"))


async def run_job(ctx, msg, code, source_link, input_size, key):
    start_time = time.time()
    await safe_edit(msg, ui_loading("Analizando", "Leyendo estructura..."))
    findings = await asyncio.to_thread(Detector.scan, code)
    top = findings[0]
    confident = top.score >= CONFIDENT
    detected_label = f"{top.label} ({int(top.score * 100)}%)" if confident else "sin identificar"

    if key == "luraph":
        luraph = next(f for f in findings if f.family == "luraph")
        await execute_plan(ctx, msg, code, source_link, input_size, engines_for(luraph), detected_label, start_time)
    else:
        await execute_plan(ctx, msg, code, source_link, input_size, [key], detected_label, start_time)


async def start_job(ctx, url, key):
    refusal = queue.check(ctx.author.id)
    if refusal:
        await ctx.send(embed=ui_error("No se puede agregar", refusal))
        return
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
    except Exception as e:
        await ctx.send(embed=ui_error("Error", str(e)[:300]))
        return
    if not code.strip():
        await ctx.send(embed=ui_error("Error", "El archivo está vacío."))
        return

    pos = queue.position_if_added()
    msg = await ctx.send(embed=ui_loading("Analizando", "Preparando trabajo...") if pos == 0 else ui_waiting(pos, *queue.stats()))

    async def work():
        await run_job(ctx, msg, code, source_link, input_size, key)

    try:
        queue.submit(Job(user_id=ctx.author.id, msg=msg, work=work, last_pos=pos))
    except QueueRefused as e:
        await safe_edit(msg, ui_error("No se puede agregar", str(e)))


# ==================== COMANDOS DEL BOT ====================
@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(
        description=(
            "# Lexy Hub • Deobf\n"
            "Usa los comandos con un **archivo adjunto**, una **URL** o **respondiendo** a un mensaje con archivo."
        ),
        color=EMBED_BLACK
    )
    embed.add_field(
        name="🔓 Desofuscadores",
        value=(
            "`.luraph` — Luraph v15 / v15.1\n"
            "`.prometheus` — Prometheus\n"
            "`.moonsec` — MoonSec V3\n"
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
            "`.queue` — estado de la cola\n"
            "`.list` — desofuscadores disponibles"
        ),
        inline=False
    )
    embed.set_footer(text="Lexy Hub Security")
    await ctx.send(embed=embed)


@bot.command(name="list")
async def cmd_list(ctx):
    list_text = (
        f"# {EMOJI_LIST} AVAILABLE DEOBFUSCATORS\n"
        "Lista de deobfuscadores activos:\n\n"
        f"**1. Luraph v15 / v15.1 {EMOJI_LURAPH} **\n"
        "• Comando: `.luraph` o `.luraph15` / `.luraph151`\n\n"
        f"**2. Prometheus {EMOJI_PROMETHEUS} **\n"
        "• Comando: `.prometheus`\n\n"
        "**3. MoonSec V3**\n"
        "• Comando: `.moonsec` (alias: `.msd`)\n\n"
        "**4. Goofyscator V11**\n"
        "• Comando: `.goofy` (alias: `.goofyscator`, `.gv11d`)"
    )
    embed = discord.Embed(description=list_text, color=EMBED_BLACK)
    await ctx.send(embed=embed)


@bot.command(name="queue")
async def cmd_queue(ctx):
    running, waiting = queue.stats()
    await ctx.send(embed=ui_ok("Cola", f"Procesando: **{running}/{queue.workers}**\nEsperando: **{waiting}/{queue.max_waiting}**"))


@bot.command(name="detect")
async def cmd_detect(ctx, url: str = None):
    msg = await ctx.send(embed=ui_loading("Analizando", "Leyendo estructura..."))
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        if not code.strip():
            raise Exception("El archivo está vacío.")
        findings = await asyncio.to_thread(Detector.scan, code)
        top = findings[0]
        
        confidence_pct = int(top.score * 100)
        
        if confidence_pct < 40:
            detect_text = (
                f"# {EMOJI_ERROR} UNKNOWN SCRIPT\n"
                f"Name: Desconocido / Sin ofuscador reconocido\n"
                f"Version: N/A\n"
                f"Confidence: {confidence_pct}%\n\n"
                f"Detected Link: {source_link}"
            )
            embed = discord.Embed(description=detect_text, color=discord.Color.red())
        else:
            version_str = "15.0"
            if "15.1" in top.label:
                version_str = "15.1"
            elif "v15" in top.label:
                version_str = "15.0"
                
            detect_text = (
                f"# {EMOJI_CORRECT} DETECTED {top.label.upper()}\n"
                f"Name: {top.label}\n"
                f"Version: {version_str}\n"
                f"Confidence: {confidence_pct}%\n\n"
                f"Detected Link: {source_link}"
            )
            embed = discord.Embed(description=detect_text, color=discord.Color.from_rgb(0, 204, 102))
            
        await safe_edit(msg, embed)
    except Exception as e:
        logger.error(f"Error en .detect: {e}", exc_info=True)
        await safe_edit(msg, ui_error("Error", str(e)[:300]))


@bot.command(name="get")
async def cmd_get(ctx, url: str = None):
    if not url:
        await ctx.send(embed=ui_error("Error", "Proporciona una URL válida."))
        return
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    msg = await ctx.send(embed=ui_loading("Conectando", "Descargando..."))
    path = f"get_{ctx.message.id}.lua"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    await safe_edit(msg, ui_error("Error HTTP", f"La URL respondió {res.status}."))
                    return
                data = await res.content.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            await safe_edit(msg, ui_error("Muy grande", f"El archivo supera {format_size(MAX_INPUT_BYTES)}."))
            return
        content = data.decode("utf-8-sig", errors="ignore")

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        fetch_text = (
            f"# {EMOJI_CORRECT} SUCCESSFULLY FETCHED\n"
            f"Fetched:\n"
            f"{url}\n\n"
            f"Download Fetched File:"
        )
        embed = discord.Embed(description=fetch_text, color=discord.Color.from_rgb(0, 204, 102))
        
        try:
            await msg.delete()
        except Exception:
            pass
            
        await ctx.send(embed=embed)
        await ctx.send(file=discord.File(path, filename="contenido.lua"))
    except Exception as e:
        await safe_edit(msg, ui_error("Error", str(e)[:300]))
    finally:
        _remove(path)


@bot.command(name="beautify")
async def cmd_beautify(ctx, url: str = None):
    start_time = time.time()
    msg = await ctx.send(embed=ui_loading("Optimizando", "Formateando código..."))
    path = f"beautify_{ctx.message.id}.lua"
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        ready_code = await asyncio.to_thread(LuauOptimizer.beautify, code)
        final_text = f"-- Deobfuscado por Lexy Deobf\n\n{ready_code}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(final_text)
        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time
        body = (
            f"**Output Preview**\n"
            f"```lua\n{make_preview(final_text)}\n```\n"
            f"Source: {source_link}\n"
            f"-# input: {format_size(input_size)} · output: {format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            f"**Output File:**"
        )
        try:
            await msg.delete()
        except Exception:
            pass
        await ctx.send(embed=ui_ok("LUA SCRIPT BEAUTIFIED", body))
        await ctx.send(file=discord.File(path, filename="executable_script.lua"))
    except Exception as e:
        logger.error(f"Error en .beautify: {e}", exc_info=True)
        await safe_edit(msg, ui_error("Error", str(e)[:300]))
    finally:
        _remove(path)


# ==================== COMANDOS DE DESOFUSCACIÓN ====================
@bot.command(name="luraph")
async def cmd_luraph(ctx, url: str = None):
    await start_job(ctx, url, "luraph")


@bot.command(name="luraph15")
async def cmd_luraph15(ctx, url: str = None):
    await start_job(ctx, url, "luraph15")


@bot.command(name="luraph151")
async def cmd_luraph151(ctx, url: str = None):
    await start_job(ctx, url, "luraph151")


@bot.command(name="prometheus")
async def cmd_prometheus(ctx, url: str = None):
    await start_job(ctx, url, "prometheus")


@bot.command(name="moonsec", aliases=["msd"])
async def cmd_moonsec(ctx, url: str = None):
    await start_job(ctx, url, "moonsec")


@bot.command(name="goofy", aliases=["goofyscator", "gv11d"])
async def cmd_goofy(ctx, url: str = None):
    await start_job(ctx, url, "goofy")


# ==================== INICIO ====================
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        logger.critical("¡Falta la variable de entorno DISCORD_TOKEN!")
    else:
        bot.run(TOKEN)
