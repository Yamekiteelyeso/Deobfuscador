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
EMOJI_CORRECT = "<:correct:1561435171385909288>"
EMOJI_ERROR = "<:error:1561510204393136209>"

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

# ==================== HERRAMIENTAS Y DIRECTORIOS ====================
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

GOOFY_ZIP = "goofyscator-deobf.zip"
GOOFY_DIR = "goofyscator-deobf"
GOOFY_ENGINES = os.path.join(GOOFY_DIR, "engines")
GOOFY_BIN = os.path.join(GOOFY_ENGINES, "deobfuscator", "deobf", "bin")
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


def chmod_exec(folder, names):
    for name in names:
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o755)
            except Exception as e:
                logger.error(f"No se pudo dar permisos a {p}: {e}")


extract_zip(LURAPH_ZIP, LURAPH_DIR, LURAPH_DIR)
extract_zip(PROM_ZIP, PROM_DIR)
extract_zip(MOON_ZIP, MOON_DIR)
extract_zip(GOOFY_ZIP, GOOFY_DIR)
extract_zip(LURAPH15_ZIP, LURAPH15_DIR)

chmod_exec(LURAPH15_BIN, ("luau", "luau-ast"))
if os.path.isdir(GOOFY_ENGINES):
    chmod_exec(GOOFY_BIN, ("luau", "luau-ast"))
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


# ==================== UI HELPERS ====================
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


def make_preview(text, max_lines=10, max_line_len=110, max_total=900):
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


# ==================== OBTENER ARCHIVO / URL ====================
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


# ==================== DETECTOR AVANZADO ====================
@dataclass
class Finding:
    family: str
    label: str
    score: float
    evidence: list = field(default_factory=list)
    hint: str = ""


FAMILY_LABEL = {
    "luraph": "Luraph v15 / v15.1",
    "prometheus": "Prometheus",
    "moonsec": "MoonSec V3",
    "goofy": "Goofyscator V11",
    "ironbrew": "IronBrew 1",
}
CONFIDENT = 0.45

LUR_TREE = re.compile(r"\b[A-Za-z_]\w*\s*<=\s*\d+\s+then\s+if\s+[A-Za-z_]\w*\s*<=\s*\d+\s+then")
LUR_CONT = re.compile(r"\bcontinue\s*;")
LUR_COLON = re.compile(r"\b[A-Za-z_]\w?:[A-Za-z_]\w?\(")
LUR_SLOTS = re.compile(r"\[\d+\]\s*=\s*(?:bit32|buffer|string|table|math)\.\w+")
LUR_START = re.compile(r"\A\s*(?:--[^\n]*\n\s*)*return\s+setmetatable\s*\(\s*\{")
LUR_LOOP = re.compile(r"while\s+[A-Za-z_]\w*\s+do\s+if\s+[A-Za-z_]\w*\s*<=\s*\d+\s+then")
LUR_HEADER = re.compile(r"Luraph Obfuscator v(\d+)\.(\d+)", re.I)

MOON_PREFIX = re.compile(r"[\"']\\4\\8")
MOON_CALL = re.compile(r"\(\s*\d+\s*,\s*[\"'](?:\\\d{1,3}){8,}")
MOON_ESC = re.compile(r"(?:\\\d{1,3}){40,}")
LOCAL_FUNC = re.compile(r"\blocal\s+function\b")

GOOFY_START = re.compile(r"\A\s*(?:--[^\n]*\n\s*)*return\s*\{")
WHILE_TRUE = re.compile(r"while\s+true\s+do")

IB_PARAMS = re.compile(r"\breturn\s*\(\s*function\s*\(\s*(?:[A-Za-z_]\w*\s*,\s*){15,}")
IB_NUMTABLE = re.compile(r"\blocal\s+[A-Za-z_]\w*\s*=\s*\{\s*-?\d+(?:\s*,\s*-?\d+){20,}")

PROM_WRAP = re.compile(r"\A\s*(?:--[^\n]*\n\s*)*return\s*\(?\s*function\s*\(\s*\.\.\.\s*\)")
PROM_SELECT = re.compile(r"select\s*\(\s*[\"']#[\"']\s*,\s*\.\.\.\s*\)")


class Detector:
    @staticmethod
    def _sample(code):
        if len(code) <= 4_000_000:
            return code
        return code[:2_000_000] + "\n" + code[-2_000_000:]

    @staticmethod
    def _luraph(s):
        score, ev, hint = 0.0, [], ""
        tree = len(LUR_TREE.findall(s))
        if tree >= 15:
            score += 0.35; ev.append(f"Árbol binario VM ({tree})")
        elif tree >= 3:
            score += 0.20; ev.append(f"Árbol binario VM ({tree})")
        cont = len(LUR_CONT.findall(s))
        if cont >= 10:
            score += 0.20; ev.append(f"continue en handlers ({cont})")
        slots = len(LUR_SLOTS.findall(s))
        if slots >= 4:
            score += 0.15; ev.append(f"Librerías indexadas ({slots})")
        if LUR_START.match(s[:3000]):
            score += 0.30; ev.append("setmetatable wrapper")
        if LUR_LOOP.search(s):
            score += 0.15; ev.append("while op dispatch")
        m = LUR_HEADER.search(s[:1500])
        if m:
            score = 1.0
            hint = f"{m.group(1)}.{m.group(2)}"
            ev.insert(0, f"Luraph v{hint}")
        return min(score, 1.0), ev, hint

    @staticmethod
    def _moonsec(s):
        score, ev = 0.0, []
        if MOON_PREFIX.search(s):
            score += 0.55; ev.append("Prefijo \\4\\8")
        if MOON_CALL.search(s):
            score += 0.20; ev.append("Llamadas cifradas MoonSec")
        if MOON_ESC.search(s):
            score += 0.20; ev.append("Escapes decimales")
        if "moonsec" in s.lower() or "moonveil" in s.lower():
            score = 1.0
            ev.insert(0, "Firma MoonSec")
        return min(score, 1.0), ev

    @staticmethod
    def _goofy(s):
        score, ev = 0.0, []
        if "limitedstack" in s:
            score += 0.45; ev.append("limitedstack")
        if "cannot change environment" in s:
            score += 0.20; ev.append("cannot change environment")
        if GOOFY_BANNER.search(s[:3000]):
            score = 1.0
            ev.insert(0, "Goofyscator V11 Banner")
        return min(score, 1.0), ev

    @staticmethod
    def _ironbrew(s, tree):
        score, ev = 0.0, []
        if IB_PARAMS.search(s):
            score += 0.60; ev.append("IronBrew params")
        if IB_NUMTABLE.search(s):
            score += 0.30; ev.append("IronBrew tabla numérica")
        return min(score, 1.0), ev

    @staticmethod
    def _prometheus(s):
        score, ev = 0.0, []
        marks = s[:4000].lower() + " " + s[-1500:].lower()
        if "prometheus" in marks or "levno" in marks:
            score += 0.85; ev.append("Prometheus marca")
        return min(score, 1.0), ev

    @staticmethod
    def scan(code):
        s = Detector._sample(code)
        findings = []

        l_score, l_ev, l_hint = Detector._luraph(s)
        label = FAMILY_LABEL["luraph"]
        if l_hint == "15.1":
            label = "Luraph v15.1"
        elif l_hint.startswith("15.0"):
            label = "Luraph v15"
        findings.append(Finding("luraph", label, l_score, l_ev, l_hint))

        m_score, m_ev = Detector._moonsec(s)
        findings.append(Finding("moonsec", FAMILY_LABEL["moonsec"], m_score, m_ev))

        g_score, g_ev = Detector._goofy(s)
        findings.append(Finding("goofy", FAMILY_LABEL["goofy"], g_score, g_ev))

        tree = len(LUR_TREE.findall(s))
        i_score, i_ev = Detector._ironbrew(s, tree)
        findings.append(Finding("ironbrew", FAMILY_LABEL["ironbrew"], i_score, i_ev))

        p_score, p_ev = Detector._prometheus(s)
        findings.append(Finding("prometheus", FAMILY_LABEL["prometheus"], p_score, p_ev))

        findings.sort(key=lambda f: f.score, reverse=True)
        return findings


# ==================== BEAUTIFIER Y OPTIMIZADOR ====================
class LuauOptimizer:
    @staticmethod
    def deep_clean_and_fix(code):
        fixed_code = code.replace("if nil == 1 then", "if 1 == 1 then").replace("elseif nil == 2 then", "elseif 1 == 2 then")
        fixed_code = re.sub(r'local function\s+fn\d+\s*\(\s*\)\s*end', '-- [Función vacía limpiada]', fixed_code)
        cleaned = []
        for line in fixed_code.splitlines():
            if "devirt:" in line or 'error("devirt:' in line or "LPH:" in line:
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
        decrease_keywords = {"end", "until", "else", "elseif"}

        for line in optimized.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            
            first_word = stripped.split()[0].lower() if stripped else ""
            if first_word in decrease_keywords or stripped == "}":
                indent = max(0, indent - 1)

            current_indent = indent
            if stripped.startswith(("else", "elseif")) and indent > 0:
                current_indent = indent - 1

            formatted.append((tab * current_indent) + stripped)

            lower = stripped.lower()
            opens = 0
            if any(lower.startswith(kw) for kw in {"if ", "for ", "while ", "function ", "local function ", "repeat"}):
                if lower.endswith(("do", "then", "repeat")) or "function(" in lower or lower.endswith("function"):
                    opens += 1
            if stripped in {"do", "repeat"} or stripped.endswith("{") or lower.startswith("else") or lower.startswith("elseif"):
                opens += 1
            
            indent += opens
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
    tool = os.path.join(LURAPH_DIR, "v15_tool_attempt_source", "deob.js")
    node_bin = _node()
    if not node_bin:
        raise MissingDependency("Node.js (`node`)")
    if not os.path.isfile(tool):
        raise MissingDependency(f"archivos de `{LURAPH_ZIP}`")

    input_file = f"input_151_{uid}.lua"
    output_file = f"output_151_{uid}.lua"
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
            raise DeobfError("Luraph v15.1 no produjo salida válida.")
        return LuauOptimizer.beautify(result_code)
    finally:
        _remove(input_file, output_file, json_path, expected_path)


async def engine_luraph15(code, uid, timeout):
    if not os.path.isfile(LURAPH15_SCRIPT):
        raise MissingDependency(f"archivos de `{LURAPH15_ZIP}` en `{LURAPH15_DIR}`")
    
    for bin_name in ("luau", "luau-ast"):
        bin_path = os.path.join(LURAPH15_BIN, bin_name)
        if not os.path.isfile(bin_path):
            raise MissingDependency(f"Falta el binario requerido `{bin_name}` en `{LURAPH15_BIN}`")

    work_dir = tempfile.mkdtemp(prefix=f"lph15_{uid}_")
    try:
        input_file = os.path.join(work_dir, "input.lua")
        output_file = os.path.join(work_dir, "output.lua")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(code)

        deadline = asyncio.get_running_loop().time() + timeout
        
        await run_stage(
            [sys.executable, os.path.abspath(LURAPH15_SCRIPT), input_file, "-o", output_file, "--obfuscator", "luraph_v15"],
            deadline, "Luraph v15", cwd=LURAPH15_DIR
        )
        
        if not os.path.isfile(output_file):
            raise DeobfError("El desofuscador Luraph v15 no generó el archivo de salida.")
            
        with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
            
        if not result_code.strip():
            raise DeobfError("Luraph v15 produjo una salida vacía.")
            
        return LuauOptimizer.beautify(result_code)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def engine_prometheus(code, uid, timeout):
    tool = os.path.join(PROM_DIR, "bin", "pdeobf.js")
    node_bin = _node()
    if not node_bin:
        raise MissingDependency("Node.js (`node`)")
    if not os.path.isfile(tool):
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
            raise DeobfError(f"Prometheus falló: {detail[-200:]}")
        return LuauOptimizer.beautify(result_code)
    finally:
        _remove(input_file, output_file)


async def engine_moonveil(code, uid, timeout):
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
    if not os.path.isfile(os.path.join(GOOFY_ENGINES, "goofyscator", "cli.mjs")):
        missing.append(f"archivos de `{GOOFY_ZIP}`")
    if not tsx_cmd:
        missing.append("Node.js + `tsx`")
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
        cli = os.path.abspath(os.path.join(GOOFY_ENGINES, "goofyscator", "cli.mjs"))
        stdout, stderr = await run_stage(
            tsx_cmd + [cli, os.path.abspath(input_file), os.path.abspath(analysis_file)],
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
        if not result_code.strip():
            raise DeobfError("Goofyscator produjo salida vacía.")
        return result_code.strip()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


ENGINES = {
    "luraph15":   {"label": "Luraph v15",   "family": "luraph",     "fn": engine_luraph15,   "title": "LURAPH V15 DEOBFUSCATED"},
    "luraph151":  {"label": "Luraph v15.1", "family": "luraph",     "fn": engine_luraph151,  "title": "LURAPH V15.1 DEOBFUSCATED"},
    "prometheus": {"label": "Prometheus",   "family": "prometheus", "fn": engine_prometheus, "title": "PROMETHEUS DEOBFUSCATED"},
    "moonveil":   {"label": "MoonSec V3",   "family": "moonsec",    "fn": engine_moonveil,   "title": "MOONSEC V3 DEOBFUSCATED"},
    "goofy":      {"label": "Goofyscator",  "family": "goofy",      "fn": engine_goofy,      "title": "GOOFYSCATOR V11 DEOBFUSCATED"},
}

FAMILY_ENGINES = {
    "luraph": ["luraph15", "luraph151"],
    "prometheus": ["prometheus"],
    "moonsec": ["moonveil"],
    "goofy": ["goofy"],
    "ironbrew": [],
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
        return False, "salida binaria o corrupta"
    if not re.search(r"\b(local|function|end|return|print|if|for|while)\b", result):
        return False, "la salida no contiene instrucciones Lua válidas"
    return True, ""


async def deliver_result(ctx, msg, title, result_code, source_link, input_size, start_time):
    final_text = f"-- Deobfuscado por Lexy Hub Bot\n\n{result_code}\n"
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
        await safe_edit(msg, ui_ok(title, body))
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
                    await safe_edit(job.msg, ui_error("Tiempo agotado", "El trabajo excedió el límite de tiempo."))
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
        f"Procesando: **{running}** · En espera: **{waiting}**\nTe avisaremos cuando inicie."
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
            failures.append((spec["label"], "tiempo agotado"))
            continue
        step = f" ({i}/{len(plan)})" if len(plan) > 1 else ""
        await safe_edit(msg, ui_loading(f"Desofuscando {spec['label']}{step}", f"Ejecutando motor..."))
        try:
            result = await spec["fn"](code, uid, min(remaining, 300))
            ok, why = await asyncio.to_thread(validate_result, code, result, spec["family"])
        except DeobfError as e:
            failures.append((spec["label"], str(e)))
            continue
        except Exception as e:
            logger.error(f"{spec['label']} error: {e}", exc_info=True)
            failures.append((spec["label"], f"error: {str(e)[:80]}"))
            continue
        if not ok:
            failures.append((spec["label"], why))
            continue

        await deliver_result(ctx, msg, spec["title"], result, source_link, input_size, start_time)
        return

    lines = "\n".join(f"**{name}:** {reason}" for name, reason in failures)
    await safe_edit(msg, ui_error("No se pudo desofuscar", f"Detectado: **{detected_label}**\n{lines}"))


async def run_job(ctx, msg, code, source_link, input_size, mode, key=None):
    start_time = time.time()
    await safe_edit(msg, ui_loading("Analizando", "Ejecutando escaneo estructural..."))
    findings = await asyncio.to_thread(Detector.scan, code)
    top = findings[0]
    confident = top.score >= CONFIDENT
    detected_label = f"{top.label} ({int(top.score * 100)}%)" if confident else "sin identificar"

    if mode == "engine":
        await execute_plan(ctx, msg, code, source_link, input_size, [key], detected_label, start_time)
        return

    if mode == "luraph":
        luraph = next(f for f in findings if f.family == "luraph")
        await execute_plan(ctx, msg, code, source_link, input_size, engines_for(luraph), detected_label, start_time)
        return


async def start_job(ctx, url, mode, key=None):
    refusal = queue.check(ctx.author.id)
    if refusal:
        await ctx.send(embed=ui_error("Rechazado", refusal))
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
    first = ui_loading("Analizando", "Preparando trabajo...") if pos == 0 else ui_waiting(pos, *queue.stats())
    msg = await ctx.send(embed=first)

    async def work():
        await run_job(ctx, msg, code, source_link, input_size, mode, key)

    job = Job(user_id=ctx.author.id, msg=msg, work=work, last_pos=pos)
    try:
        queue.submit(job)
    except QueueRefused as e:
        await safe_edit(msg, ui_error("Rechazado", str(e)))


# ==================== COMANDOS ====================
@bot.command(name="help")
async def cmd_help(ctx):
    embed = discord.Embed(
        description=(
            "# Lexy Hub • Deobf\n"
            "Usa los comandos adjuntando un archivo Luau, enviando una URL o respondiendo a un mensaje."
        ),
        color=EMBED_BLACK
    )
    embed.add_field(
        name="🔓 Motores Específicos",
        value=(
            "`.luraph` — Luraph v15 / v15.1\n"
            "`.prometheus` — Prometheus\n"
            "`.moonveil` — MoonSec V3\n"
            "`.goofy` — Goofyscator V11"
        ),
        inline=False
    )
    embed.add_field(
        name="🛠️ Utilidades",
        value=(
            "`.detect` — Análisis profundo y detección de ofuscadores\n"
            "`.beautify` — Limpia, repara e indenta código Luau\n"
            "`.get <URL>` — Descarga y muestra código en texto plano\n"
            "`.queue` — Estado actual de la cola de trabajo"
        ),
        inline=False
    )
    embed.set_footer(text="Lexy Hub Security")
    await ctx.send(embed=embed)


@bot.command(name="list")
async def cmd_list(ctx):
    embed = discord.Embed(
        description="Deobfs Disponibles:\n• Luraph v15/v15.1\n• Prometheus\n• MoonSec V3\n• Goofyscator V11",
        color=EMBED_BLACK
    )
    await ctx.send(embed=embed)


@bot.command(name="queue")
async def cmd_queue(ctx):
    running, waiting = queue.stats()
    embed = discord.Embed(
        description=f"# {EMOJI_CORRECT} QUEUE STATUS\nRunning: {running}/{queue.workers}\nWaiting: {waiting}/{queue.max_waiting}",
        color=discord.Color.from_rgb(0, 204, 102)
    )
    await ctx.send(embed=embed)


# --- FORMATO CON LÍNEAS DIVISORIAS EXACTO PARA .detect ---
@bot.command(name="detect")
async def cmd_detect(ctx, url: str = None):
    msg = await ctx.send(embed=ui_loading("Analizando", "Ejecutando escaneo exhaustivo..."))
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        if not code.strip():
            raise Exception("El archivo está vacío.")
        
        findings = await asyncio.to_thread(Detector.scan, code)
        top = findings[0]

        if top.score >= CONFIDENT:
            name_str = top.label
            version_str = top.hint or "unknown"
            conf_str = f"{int(top.score * 100)}%"
            header_name = top.label.upper().replace(" ", "_")
        else:
            name_str = "unknow"
            version_str = "unknow"
            conf_str = "0%"
            header_name = "UNKNOW"

        embed_desc = (
            f"# {EMOJI_CORRECT} DETECTED {header_name}\n"
            f"---\n"
            f"Name: {name_str}\n"
            f"Version: {version_str}\n"
            f"Confidence: {conf_str}\n"
            f"---\n"
            f"Detected Link: {source_link}"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))
        await safe_edit(msg, embed)
    except Exception as e:
        logger.error(f"Error en .detect: {e}", exc_info=True)
        embed_desc = (
            f"# {EMOJI_ERROR} DETECTED UNKNOW\n"
            f"---\n"
            f"Name: unknow\n"
            f"Version: unknow\n"
            f"Confidence: 0%\n"
            f"---\n"
            f"Detected Link: {url or 'None'}"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.red())
        await safe_edit(msg, embed)


# --- FORMATO CON LÍNEAS DIVISORIAS EXACTO PARA .get (Basado en la imagen) ---
@bot.command(name="get")
async def cmd_get(ctx, url: str = None):
    if not url:
        await ctx.send(embed=ui_error("Error", "Proporciona una URL válida."))
        return
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    msg = await ctx.send(embed=ui_loading("Conectando", "Descargando recurso..."))
    path = f"get_{ctx.message.id}.lua"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    await safe_edit(msg, ui_error("Error HTTP", f"Código de respuesta: {res.status}."))
                    return
                data = await res.content.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            await safe_edit(msg, ui_error("Archivo muy grande", f"Supera el límite de {format_size(MAX_INPUT_BYTES)}."))
            return
        content = data.decode("utf-8-sig", errors="ignore")

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        embed_desc = (
            f"# {EMOJI_CORRECT} SUCCESSFULLY\n"
            f"FETCHED\n"
            f"---\n"
            f"Fetched:\n"
            f"{url}\n"
            f"---\n"
            f"Download Fetched File:"
        )
        embed = discord.Embed(description=embed_desc, color=discord.Color.from_rgb(0, 204, 102))
        await safe_edit(msg, embed)
        await ctx.send(file=discord.File(path, filename="contenido.lua"))
    except Exception as e:
        await safe_edit(msg, ui_error("Error", str(e)[:300]))
    finally:
        _remove(path)


@bot.command(name="beautify")
async def cmd_beautify(ctx, url: str = None):
    start_time = time.time()
    msg = await ctx.send(embed=ui_loading("Optimizando", "Formateando código Luau..."))
    path = f"beautify_{ctx.message.id}.lua"
    try:
        code, source_link, input_size = await get_code_and_source(ctx, url)
        ready_code = await asyncio.to_thread(LuauOptimizer.beautify, code)
        final_text = f"-- Formateado por Lexy Hub Bot\n\n{ready_code}"
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
        await safe_edit(msg, ui_ok("LUA SCRIPT BEAUTIFIED", body))
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
    await start_job(ctx, url, "engine", "luraph15")


@bot.command(name="luraph151")
async def cmd_luraph151(ctx, url: str = None):
    await start_job(ctx, url, "engine", "luraph151")


@bot.command(name="prometheus")
async def cmd_prometheus(ctx, url: str = None):
    await start_job(ctx, url, "engine", "prometheus")


@bot.command(name="moonveil", aliases=["moonsec", "msd"])
async def cmd_moonveil(ctx, url: str = None):
    await start_job(ctx, url, "engine", "moonveil")


@bot.command(name="goofy", aliases=["goofyscator", "gv11d"])
async def cmd_goofy(ctx, url: str = None):
    await start_job(ctx, url, "engine", "goofy")


# ==================== INICIO DEL BOT ====================
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        logger.critical("¡Falta la variable de entorno DISCORD_TOKEN!")
    else:
        bot.run(TOKEN)
