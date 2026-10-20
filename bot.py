"""
Lexy Hub - Bot de desofuscación de scripts Lua / Luau para Discord.

Comandos
    .luraph / .luraph151               Luraph v15.1 (y v15 con el mismo motor)
    .prometheus                        Prometheus
    .moonveil (.moonsec .msd)          MoonSec V3
    .goofy (.goofyscator .gv11d)       Goofyscator V11
    .detect   identifica el ofuscador leyendo la estructura del código
    .analyze  perfil técnico del script
    .beautify formatea el código (formateador real, verificado)
    .get      descarga un archivo desde una URL
    .list .help .queue

Todo desofuscador pasa por una cola para que el bot no se sature.
Requiere Python 3.9+, discord.py 2.x y aiohttp.
"""
import os
import re
import sys
import json
import math
import time
import shutil
import signal
import socket
import asyncio
import logging
import zipfile
import tempfile
import ipaddress
from collections import deque, Counter
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, urljoin

import aiohttp
import discord
from discord.ext import commands

# ============================================================================
# LOGGING (consola + archivo rotativo bot.log)
# ============================================================================
_log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(RotatingFileHandler("bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
except OSError:
    pass   # hosting de solo lectura: se sigue solo con la consola

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger("LexyHubBot")


# ============================================================================
# EMOJIS
# ============================================================================
EMOJI_LOADING = "<a:loading:1561435149793493166>"
EMOJI_CORRECT = "<:correct:1561435171385909288>"
EMOJI_ERROR = "<:error:1561510204393136209>"
EMOJI_LIST = "<:list:1561778149514149888>"
EMOJI_LURAPH = "<:luraph:1561779566635126845>"
EMOJI_PROMETHEUS = "<:prometheus:1561782588022984774>"


# ============================================================================
# CONFIGURACIÓN (se puede cambiar con variables de entorno)
# ============================================================================
def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


MAX_CONCURRENT_JOBS = max(1, _env_int("MAX_CONCURRENT_JOBS", 2))   # desofuscaciones a la vez
MAX_WAITING_JOBS = max(1, _env_int("MAX_WAITING_JOBS", 15))        # personas esperando como máximo
MAX_INPUT_BYTES = max(1, _env_int("MAX_INPUT_MB", 8)) * 1024 * 1024
MAX_BEAUTIFY_BYTES = max(1, _env_int("MAX_BEAUTIFY_MB", 3)) * 1024 * 1024
HARD_JOB_TIMEOUT = 720          # tope absoluto por trabajo (segundos)
COMMAND_COOLDOWN = 4            # segundos entre usos de .detect/.beautify/.get por usuario
HTTP_TIMEOUT = 20               # segundos para descargar una URL
MAX_REDIRECTS = 3

# ============================================================================
# HERRAMIENTAS EXTERNAS (zips que se descomprimen solos junto al bot)
# ============================================================================
LURAPH_ZIP = "luraphv15_1_deobf.zip"          # motor de Luraph v15.1 (Node)
LURAPH_DIR = "v15_tool_attempt_source"

PROM_ZIP = "Prometheus-Deobfuscator-main.zip"
PROM_DIR = "Prometheus-Deobfuscator-main"

MOON_ZIP = "moonsec-v3.zip"
MOON_DIR = "moonsec-v3"
MOON_DLL = os.path.join(MOON_DIR, "bin", "Release", "net9.0", "MoonsecDeobfuscator.dll")
MOON_JAR = os.path.join(MOON_DIR, "deps", "unluac", "unluac.jar")


IB2_ZIP = "ironbrew2.zip"                      # IronBrew 2 (.NET 9 + descompilador Oracle)
IB2_DIR = "ib2bot-main"
IB2_WORK = os.path.join(IB2_DIR, "ib2deobf")
IB2_TOOL = os.path.join(IB2_WORK, "LuaAnalysis.Ironbrew2.dll")
ORACLE_KEY = os.getenv("ORACLE", "").strip()   # clave del descompilador (variable de entorno)
ORACLE_URL = os.getenv("ORACLE_URL", "https://oracle.mshq.dev/decompile").strip()

GOOFY_ZIP = "goofyscator-deobf.zip"
GOOFY_DIR = "goofyscator-deobf"
GOOFY_ENGINES = os.path.join(GOOFY_DIR, "engines")
GOOFY_BIN = os.path.join(GOOFY_ENGINES, "deobfuscator", "deobf", "bin")
GOOFY_BANNER = re.compile(r"^--[^\n]*protected by goofyscator V11 BETA-1\b", re.I)


def extract_zip(zip_path, marker_dir, target="."):
    """Descomprime zip_path en target si todavía no existe marker_dir."""
    if os.path.exists(zip_path) and not os.path.exists(marker_dir):
        logger.info(f"Descomprimiendo {zip_path}...")
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(target)
            logger.info(f"{zip_path} descomprimido con éxito.")
        except Exception as e:
            logger.error(f"Error al descomprimir {zip_path}: {e}")


def extract_ib2():
    """Extrae solo ib2deobf/ del zip de IronBrew 2. El .env y los archivos de Windows del zip no se extraen."""
    if not os.path.exists(IB2_ZIP) or os.path.isfile(IB2_TOOL):
        return
    logger.info(f"Extrayendo el deobfuscador de IronBrew 2 desde {IB2_ZIP}...")
    try:
        prefix = IB2_WORK.replace(os.sep, "/") + "/"
        with zipfile.ZipFile(IB2_ZIP, "r") as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or not name.startswith(prefix) or name.endswith(".lnk"):
                    continue
                dest = os.path.normpath(name)
                if not os.path.abspath(dest).startswith(os.path.abspath(IB2_WORK) + os.sep):
                    continue   # evita rutas que salen de la carpeta
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(info) as src_f, open(dest, "wb") as out_f:
                    shutil.copyfileobj(src_f, out_f)
        logger.info("IronBrew 2 extraído con éxito.")
    except Exception as e:
        logger.error(f"Error al extraer {IB2_ZIP}: {e}")


def chmod_exec(folder, names):
    """extractall() no conserva el permiso de ejecución de los binarios."""
    for name in names:
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o755)
            except Exception as e:
                logger.error(f"No se pudo dar permisos a {p}: {e}")


LUAU_RELEASE_URL = os.getenv("LUAU_RELEASE_URL", "").rstrip("/")   # p. ej. https://github.com/USUARIO/REPO/releases/download/luau-0.739


def ensure_luau_binaries():
    """Si faltan luau / luau-ast y LUAU_RELEASE_URL está definida, los descarga de la Release de GitHub."""
    import urllib.request
    targets = []
    if os.path.isdir(GOOFY_ENGINES):
        targets.append(GOOFY_BIN)
    for folder in targets:
        for exe in ("luau", "luau-ast"):
            path = os.path.join(folder, exe)
            if os.path.isfile(path):
                continue
            if not LUAU_RELEASE_URL:
                logger.warning(f"Falta {path}. Define LUAU_RELEASE_URL o ejecuta setup_luau.sh.")
                continue
            tmp = path + ".part"
            try:
                os.makedirs(folder, exist_ok=True)
                with urllib.request.urlopen(f"{LUAU_RELEASE_URL}/{exe}", timeout=60) as resp, open(tmp, "wb") as f:
                    shutil.copyfileobj(resp, f)
                with open(tmp, "rb") as f:
                    if f.read(4) != b"\x7fELF":
                        raise ValueError("el archivo descargado no es un binario Linux")
                os.replace(tmp, path)
                os.chmod(path, 0o755)
                logger.info(f"Descargado {path}")
            except Exception as e:
                logger.error(f"No se pudo descargar {exe}: {e}")
                if os.path.exists(tmp):
                    os.remove(tmp)


def cleanup_stale_files():
    """Borra temporales que un cierre brusco anterior pudo dejar."""
    patterns = re.compile(r"^(?:input_|output_|prom_input_|prom_output_|executable_script_|get_|beautify_|fetched_).*\.lua$")
    removed = 0
    for name in os.listdir("."):
        if patterns.match(name):
            try:
                os.remove(name)
                removed += 1
            except OSError:
                pass
    out_dir = "output"
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            if name.startswith("input_") and name.endswith(".lua"):
                try:
                    os.remove(os.path.join(out_dir, name))
                    removed += 1
                except OSError:
                    pass
    if removed:
        logger.info(f"Se limpiaron {removed} archivos temporales antiguos.")


extract_zip(LURAPH_ZIP, LURAPH_DIR, LURAPH_DIR)
extract_zip(PROM_ZIP, PROM_DIR)
extract_zip(MOON_ZIP, MOON_DIR)
extract_zip(GOOFY_ZIP, GOOFY_DIR)
extract_ib2()

if os.path.isdir(GOOFY_ENGINES):
    chmod_exec(GOOFY_BIN, ("luau", "luau-ast"))
    # El zip no trae package.json: sin "type": "module" los .ts/.mjs no resuelven sus imports.
    try:
        _pkg = os.path.join(GOOFY_ENGINES, "package.json")
        if not os.path.exists(_pkg):
            with open(_pkg, "w", encoding="utf-8") as _f:
                _f.write('{"type":"module"}\n')
    except Exception as e:
        logger.error(f"Error preparando Goofyscator: {e}")

ensure_luau_binaries()
cleanup_stale_files()

# ============================================================================
# BOT
# ============================================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# 0x000000 se ve como "sin color"; 0x010101 pinta la franja realmente negra.
EMBED_COLOR = discord.Color.from_rgb(1, 1, 1)   # embeds neutros (carga, listas)
COLOR_OK = discord.Color.from_rgb(46, 204, 113)  # verde: salió bien
COLOR_ERR = discord.Color.from_rgb(231, 76, 60)  # rojo: falló

STATS = {"started": time.time(), "jobs_ok": 0, "jobs_failed": 0}


@bot.event
async def on_ready():
    logger.info(f"¡Bot conectado exitosamente como {bot.user}!")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="scripts Luau | .help")
    )


@bot.event
async def on_message(message):
    """Registra cada comando recibido y luego lo procesa (al sobrescribir on_message hay que hacerlo)."""
    if message.author.bot:
        return
    if message.content.startswith("."):
        logger.info(f"Comando de {message.author} en {message.guild or 'DM'}: {message.content[:80]}")
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CommandOnCooldown):
        await send_embed(ctx, e_err("COOLDOWN", f"Espera {error.retry_after:.0f}s antes de volver a usar este comando."))
        return
    original = getattr(error, "original", error)
    logger.error(f"Error en comando {getattr(ctx.command, 'name', '?')}: {original}", exc_info=original)
    # Que el usuario siempre vea un mensaje, aunque el error no esté controlado.
    try:
        await send_embed(ctx, e_err("ERROR", f"```{str(original)[:300]}```"))
    except Exception as e:
        logger.error(f"No pude avisar el error al usuario: {e}")


# ============================================================================
# EMBEDS: todos comparten el mismo estilo (encabezado grande + líneas "Clave: valor")
# ============================================================================
def clamp(text, limit=4000):
    """Recorta a `limit` sin dejar un bloque ``` abierto (rompería el render del embed)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    nl = cut.rfind("\n")
    if nl > limit // 2:
        cut = cut[:nl]
    if cut.count("```") % 2 == 1:
        cut += "\n```"
    return cut


def build_embed(head, body="", emoji=EMOJI_CORRECT, color=EMBED_COLOR):
    desc = f"# {emoji} {head}"
    if body:
        desc += f"\n{body}"
    return discord.Embed(description=clamp(desc), color=color)


def e_ok(head, body=""):
    return build_embed(head, body, EMOJI_CORRECT, COLOR_OK)


def e_err(head, body=""):
    return build_embed(head, body, EMOJI_ERROR, COLOR_ERR)


def e_load(head, body=""):
    return build_embed(head, body, EMOJI_LOADING, EMBED_COLOR)


def e_list(head, body=""):
    return build_embed(head, body, EMOJI_LIST, EMBED_COLOR)


def plain_text(embed):
    """Versión en texto del embed (por si el bot no tiene permiso de insertar embeds)."""
    lines = (embed.description or "").split("\n")
    if lines and lines[0].startswith("#"):
        lines[0] = "**" + lines[0].lstrip("# ").strip() + "**"
    return "\n".join(lines)


async def send_embed(ctx, embed):
    """Envía respondiendo al comando (sin mencionar). Si falla el embed, cae a texto plano."""
    ref = None
    to_ref = getattr(ctx.message, "to_reference", None)
    if to_ref is not None:
        try:
            ref = to_ref(fail_if_not_exists=False)
        except Exception:
            ref = None
    try:
        return await ctx.send(embed=embed, reference=ref, mention_author=False)
    except discord.Forbidden:
        return await ctx.send(plain_text(embed)[:1900])


async def send_file(ctx, path, filename):
    """El archivo va en un mensaje aparte, justo debajo del embed."""
    return await ctx.send(file=discord.File(path, filename=filename))


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


def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def make_preview(text, max_lines=8, max_line_len=110, max_total=900):
    """Vista previa segura para el embed: líneas recortadas y sin romper el bloque de código."""
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


def _remove(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


# ============================================================================
# ENTRADA: adjunto / respuesta / bloque de código / URL
# ============================================================================
class InputError(Exception):
    """Problema con el archivo o la URL del usuario (el mensaje se muestra tal cual)."""


@dataclass
class Source:
    text: str
    raw: bytes
    link: str          # lo que se muestra en "Detected Link" / "Fetched"
    size: int
    origin: str        # attachment | reply | code | url


URL_RE = re.compile(r"^(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?(?:/\S*)?$")
FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n?(.*?)```", re.S)


def decode_bytes(raw):
    return raw.decode("utf-8-sig", errors="ignore")


def normalize_url(raw):
    """Convierte enlaces de páginas (pastebin, github blob...) en su versión de texto plano."""
    url = raw.strip().strip("<>")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path

    if host in ("pastebin.com", "www.pastebin.com"):
        m = re.fullmatch(r"/(?!raw/)(?:u/[^/]+/)?([A-Za-z0-9]{6,12})/?", path)
        if m:
            return f"https://pastebin.com/raw/{m.group(1)}"
    elif host in ("github.com", "www.github.com"):
        m = re.fullmatch(r"/([^/]+)/([^/]+)/blob/(.+)", path)
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    elif host == "gist.github.com":
        m = re.fullmatch(r"/([^/]+)/([0-9a-f]{20,40})/?", path)
        if m:
            return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw"
    elif host in ("hastebin.com", "www.hastebin.com", "rentry.co", "paste.ee"):
        m = re.fullmatch(r"/([A-Za-z0-9_-]+)/?", path)
        if m:
            return f"https://{host}/raw/{m.group(1)}"
    return url


def _is_public_ip(ip_text):
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return ip.is_global


def _resolve_public(host):
    """True si TODAS las direcciones del host son públicas (evita que el bot toque la red interna)."""
    if not host or host.lower() in ("localhost",) or host.lower().endswith((".local", ".internal")):
        return False
    try:
        ipaddress.ip_address(host)
        return _is_public_ip(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addrs = {i[4][0] for i in infos}
    return bool(addrs) and all(_is_public_ip(a) for a in addrs)


async def http_fetch(url, max_bytes):
    """GET con redirecciones manuales (cada salto se valida) y límite de tamaño. Devuelve bytes."""
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LexyHub/1.0)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise InputError("Solo se permiten URLs http/https.")
            if not await asyncio.to_thread(_resolve_public, parsed.hostname):
                raise InputError("Esa dirección no es pública o no se pudo resolver.")
            async with session.get(url, allow_redirects=False) as res:
                if res.status in (301, 302, 303, 307, 308):
                    loc = res.headers.get("Location")
                    if not loc:
                        raise InputError("Redirección inválida.")
                    url = urljoin(url, loc)
                    continue
                if res.status != 200:
                    raise InputError(f"La URL respondió HTTP {res.status}.")
                declared = res.content_length
                if declared and declared > max_bytes:
                    raise InputError(f"El archivo pesa {format_size(declared)} y el máximo es {format_size(max_bytes)}.")
                chunks, total = [], 0
                async for chunk in res.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise InputError(f"El archivo supera el máximo de {format_size(max_bytes)}.")
                    chunks.append(chunk)
                return b"".join(chunks), url
        raise InputError("Demasiadas redirecciones.")


def parse_arg(arg):
    """Interpreta el texto que sigue al comando: ('code', texto) | ('url', url) | None."""
    if not arg or not arg.strip():
        return None
    a = arg.strip()
    m = FENCE_RE.search(a)
    if m:
        return ("code", m.group(1))
    parts = a.split()
    if len(parts) == 1 and URL_RE.match(parts[0].strip("<>")):
        return ("url", parts[0].strip("<>"))
    if any(c in a for c in "=()\n"):
        return ("code", a)
    raise InputError("No entendí eso. Adjunta un archivo, responde a uno, pega una URL o un bloque de código.")


async def _read_attachment(att):
    if att.size > MAX_INPUT_BYTES:
        raise InputError(f"El archivo pesa {format_size(att.size)} y el máximo es {format_size(MAX_INPUT_BYTES)}.")
    raw = await att.read()
    return Source(decode_bytes(raw), raw, att.url, len(raw), "attachment")


async def get_source(ctx, arg=None):
    """Obtiene el script del usuario. Prioridad: adjunto > mensaje respondido > texto/URL del comando."""
    if ctx.message.attachments:
        return await _read_attachment(ctx.message.attachments[0])

    ref = ctx.message.reference
    if ref and ref.message_id:
        try:
            ref_msg = await ctx.channel.fetch_message(ref.message_id)
        except Exception as e:
            logger.warning(f"No se pudo leer el mensaje respondido: {e}")
            ref_msg = None
        if ref_msg is not None:
            if ref_msg.attachments:
                src = await _read_attachment(ref_msg.attachments[0])
                src.origin = "reply"
                return src
            m = FENCE_RE.search(ref_msg.content or "")
            if m:
                raw = m.group(1).encode("utf-8")
                return Source(m.group(1), raw, "Pasted code", len(raw), "reply")

    parsed = parse_arg(arg)
    if parsed:
        kind, value = parsed
        if kind == "code":
            raw = value.encode("utf-8")
            if len(raw) > MAX_INPUT_BYTES:
                raise InputError(f"El texto supera el máximo de {format_size(MAX_INPUT_BYTES)}.")
            return Source(value, raw, "Pasted code", len(raw), "code")
        url = normalize_url(value)
        raw, final_url = await http_fetch(url, MAX_INPUT_BYTES)
        return Source(decode_bytes(raw), raw, final_url, len(raw), "url")

    raise InputError("No encontré un archivo adjunto, un mensaje respondido con archivo, una URL ni código.")


# ============================================================================
# LEXER DE LUA / LUAU
# ============================================================================
LUA_KEYWORDS = frozenset(
    "and break do else elseif end false for function goto if in local nil not or repeat return then true until while".split()
)

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<bcomment>--\[(?P<ceq>=*)\[.*?\](?P=ceq)\])
  | (?P<lcomment>--[^\n]*)
  | (?P<lstr>\[(?P<seq>=*)\[.*?\](?P=seq)\])
  | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<bt>`(?:[^`\\]|\\.)*`)
  | (?P<num>0[xX][0-9a-fA-F_]*(?:\.[0-9a-fA-F_]*)?(?:[pP][+-]?[0-9_]+)?
          |0[bB][01_]+
          |(?:[0-9][0-9_]*(?:\.(?!\.)[0-9_]*)?|\.[0-9][0-9_]*)(?:[eE][+-]?[0-9_]+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\.\.|\.\.=|//=|==|~=|<=|>=|<<|>>|::|->|\+=|-=|\*=|/=|%=|\^=|\.\.|//|[-+*/%^\#<>=(){}\[\];:,.~&|?!@\\$])
    """,
    re.S | re.X,
)


class LexError(Exception):
    pass


class Tok:
    """Token: k=tipo, t=texto, nl=había salto de línea antes, sp=había espacio, blank=línea en blanco antes."""
    __slots__ = ("k", "t", "nl", "sp", "blank", "x")

    def __init__(self, k, t, nl, sp, blank):
        self.k = k
        self.t = t
        self.nl = nl
        self.sp = sp
        self.blank = blank
        self.x = None


def tokenize(code, lenient=False):
    """Divide el código en tokens. En modo estricto lanza LexError ante algo que no entiende."""
    toks = []
    append = toks.append
    match = _TOKEN_RE.match
    pos, n = 0, len(code)
    nl = sp = blank = False
    while pos < n:
        m = match(code, pos)
        if m is None:
            if not lenient:
                raise LexError(f"carácter inesperado {code[pos]!r} en la posición {pos}")
            append(Tok("other", code[pos], nl, sp, blank))
            nl = sp = blank = False
            pos += 1
            continue
        kind = m.lastgroup
        end = m.end()
        if kind == "ws":
            sp = True
            newlines = code.count("\n", pos, end)
            if newlines:
                nl = True
                if newlines >= 2:
                    blank = True
            pos = end
            continue
        text = m.group()
        if kind == "name":
            k = "kw" if text in LUA_KEYWORDS else "name"
        elif kind in ("bcomment", "lcomment"):
            k = "comment"
        elif kind in ("lstr", "str", "bt"):
            k = "str"
        else:
            k = kind
        append(Tok(k, text, nl, sp, blank))
        nl = sp = blank = False
        pos = end
    return toks


# ============================================================================
# FORMATEADOR
# ============================================================================
BINOPS = frozenset([
    "+", "-", "*", "/", "//", "%", "^", "..", "==", "~=", "<", ">", "<=", ">=", "<<", ">>", "&", "|",
    "=", "+=", "-=", "*=", "/=", "%=", "^=", "..=", "//=", "->",
])
CONT_OPS = frozenset(["..", "+", "-", "*", "/", "//", "%", "^", "==", "~=", "<", ">", "<=", ">=", "<<", ">>", "&", "|"])
VALUE_KW = frozenset(["end", "true", "false", "nil", "break"])
CLOSERS = frozenset([")", "]", "}"])
KW_BEFORE_PAREN = frozenset(["and", "or", "not", "if", "elseif", "while", "until", "return", "in", "then", "do", "else", "local", "for", "repeat"])
IFX_END_KW = frozenset(["local", "for", "while", "repeat", "return", "break", "goto", "end", "until", "do"])
OPCHARS = frozenset("=<>~-+*/%^.:&|")
STMT_STARTERS = frozenset(["local", "for", "while", "repeat", "return", "break", "goto", "function", "if"])


def value_end(p):
    """True si el token p termina una expresión (lo siguiente ya no puede continuarla con un nombre)."""
    if p is None:
        return False
    k = p.k
    if k in ("name", "num", "str"):
        return True
    if k == "op":
        return p.t in (")", "]", "}", "...")
    if k == "kw":
        return p.t in VALUE_KW
    return False


def _is_word(tok):
    return tok.k in ("name", "kw", "num")


def _skip_group(toks, j):
    """j apunta a ( { [ : devuelve el índice posterior al cierre correspondiente."""
    n, depth = len(toks), 0
    while j < n:
        t = toks[j]
        if t.k == "op":
            if t.t in ("(", "{", "["):
                depth += 1
            elif t.t in (")", "}", "]"):
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    return n


def _skip_type(toks, j):
    """Salta una anotación de tipo de Luau que empieza en j. Devuelve el índice posterior."""
    n = len(toks)

    def one(j):
        if j >= n:
            return j
        t = toks[j]
        if t.k == "op" and t.t in ("(", "{", "["):
            return _skip_group(toks, j)
        if t.k in ("name", "str") or (t.k == "kw" and t.t in ("nil", "true", "false")):
            is_typeof = t.k == "name" and t.t == "typeof"
            j += 1
            while j < n:
                u = toks[j]
                if u.k == "op" and u.t == "." and j + 1 < n and toks[j + 1].k == "name":
                    j += 2
                    continue
                if u.k == "op" and u.t == "<":
                    depth = 0
                    while j < n:
                        v = toks[j]
                        if v.k == "op":
                            if v.t == "<":
                                depth += 1
                            elif v.t == ">":
                                depth -= 1
                            elif v.t == ">>":
                                depth -= 2
                            if depth <= 0:
                                j += 1
                                break
                        j += 1
                    continue
                if is_typeof and u.k == "op" and u.t == "(":
                    j = _skip_group(toks, j)
                    is_typeof = False
                    continue
                break
            return j
        return j + 1

    j = one(j)
    while j < n and toks[j].k == "op" and toks[j].t in ("?", "|", "&", "->"):
        j = one(j + 1)
    return j


def _header_end(toks, i):
    """Para el `function` en i: índice del primer token del cuerpo (tras parámetros y tipo de retorno)."""
    n = len(toks)
    j = i + 1
    while j < n and not (toks[j].k == "op" and toks[j].t == "("):
        t = toks[j]
        if t.k == "kw" or (t.k == "op" and t.t not in (".", ":", "<", ">", ",", "...")) or t.k in ("num", "str"):
            return None
        j += 1
        if j - i > 60:
            return None
    if j >= n:
        return None
    j = _skip_group(toks, j)
    if j < n and toks[j].k == "op" and toks[j].t == ":":
        j = _skip_type(toks, j + 1)
    return j


class _Formatter:
    INDENT = "    "
    WRAP = 100        # ancho al que se parten las tablas largas de datos

    def __init__(self, toks):
        self.toks = toks
        self.n = len(toks)
        self.lines = []
        self.cur = []
        self.cur_len = 0
        self.line_indent = 0
        self.indent = 0
        self.cont = False          # la próxima línea es continuación (sangría +1)
        self.stack = []            # P ( [ | T { | F función | FE función vacía | IF | LOOP | DO | REP | IFX if-expresión
        self.bdepth = 0
        self.pending = None        # salto de línea diferido: 'stmt' | 'tbl' | 'cmt'
        self.stmt_start = True
        self.pv = None             # último token significativo emitido
        self.pv_unary = False
        self.no_break = 0
        self.func_hend = -1
        self.tbl = {}
        self._prepare()

    # ------------------------------------------------------------------ preparación
    def _prepare(self):
        toks, n = self.toks, self.n
        pf = [0] * (n + 1)
        pc = [0] * (n + 1)
        pl = [0] * (n + 1)
        pt = [0] * (n + 1)
        for i, t in enumerate(toks):
            pf[i + 1] = pf[i] + (1 if t.k == "kw" and t.t == "function" else 0)
            pc[i + 1] = pc[i] + (1 if t.k == "comment" else 0)
            pl[i + 1] = pl[i] + len(t.t) + 1
            pt[i + 1] = pt[i] + (1 if t.k == "op" and t.t == "{" else 0)
        opens = []
        for i, t in enumerate(toks):
            if t.k == "op":
                if t.t == "{":
                    opens.append(i)
                elif t.t == "}" and opens:
                    j = opens.pop()
                    funcs = pf[i] - pf[j + 1]
                    comments = pc[i] - pc[j + 1]
                    length = pl[i] - pl[j + 1]
                    nested = pt[i] - pt[j + 1]
                    empty = i == j + 1
                    multi = (not empty) and (
                        funcs > 0 or comments > 0 or length > 80 or (toks[j + 1].nl and toks[i].nl)
                    )
                    self.tbl[j] = (multi, funcs == 0 and nested == 0)
                elif t.t == ":" and i + 2 < n:
                    a, b = toks[i + 1], toks[i + 2]
                    is_method = a.k == "name" and (b.t in ("(", "{") or b.k == "str")
                    t.x = "m" if is_method else "a"

    # ------------------------------------------------------------------ salida
    def flush(self):
        if self.cur:
            self.lines.append(self.INDENT * self.line_indent + "".join(self.cur))
            self.cur = []
            self.cur_len = 0

    def blank(self):
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def put(self, txt, space):
        if not self.cur:
            self.line_indent = self.indent + (1 if self.cont else 0)
            self.cont = False
        elif space:
            self.cur.append(" ")
            self.cur_len += 1
        self.cur.append(txt)
        self.cur_len += len(txt)

    # ------------------------------------------------------------------ espaciado
    def _space(self, p, c):
        pt, ct = p.t, c.t
        res = self._space_raw(p, c, pt, ct)
        if not res:
            a, b = pt[-1:], ct[:1]
            if (a == "-" and b == "-") or (a == "[" and b in ("[", "=")) or (a in OPCHARS and b in OPCHARS and a != "." and b != "."):
                return True
        return res

    def _space_raw(self, p, c, pt, ct):
        pk, ck = p.k, c.k
        if self.pv_unary:
            return pt == ct and pt in ("-", "~")
        if pk == "op":
            if pt in ("(", "["):
                return False
            if pt == "{":
                return False
            if pt == ".":
                return False
            if pt == ":":
                return p.x == "a"
            if pt == "::":
                return c.sp
        if ck == "op":
            if ct in CLOSERS or ct in (",", ";", ".", ":", "?"):
                return False
            if ct == "::":
                return c.sp
        if pt == "," or pt == ";":
            return True
        if ct == "(":
            if pk == "name" or pk == "str" or pt in (")", "]", "}"):
                return False
            if pk == "kw":
                return pt in KW_BEFORE_PAREN
            if pk == "op":
                return True
            return c.sp
        if ct == "[":
            if value_end(p):
                return False
            return True
        if (ck == "op" and ct in BINOPS) or (pk == "op" and pt in BINOPS):
            return True
        if ck == "kw":
            return True
        if pk == "kw" and pt not in ("true", "false", "nil", "end"):
            return True
        if _is_word(p) and _is_word(c):
            return True
        return c.sp

    # ------------------------------------------------------------------ emisión de un token
    def _emit(self, t):
        pv = self.pv
        space = bool(self.cur) and pv is not None and self._space(pv, t)
        self.put(t.t, space)
        self.pv_unary = t.k == "op" and (t.t == "#" or (t.t in ("-", "~") and not value_end(pv)))
        self.pv = t
        self.stmt_start = False
        if t.k == "name" and self.no_break:
            self.no_break -= 1

    # ------------------------------------------------------------------ pila
    def _pop_ifx(self, k, tx, pv):
        st = self.stack
        while st and st[-1][0] == "IFX":
            if k == "op" and (tx in CLOSERS or tx in (",", ";")):
                st.pop()
            elif k == "kw" and tx in IFX_END_KW:
                st.pop()
            elif k == "kw" and tx in ("else", "elseif") and st[-1][1]:
                st.pop()           # esa if-expresión ya tuvo su `else`: este pertenece a un `if` exterior
            elif value_end(pv) and ((k == "name" and not self.no_break) or (k == "kw" and tx in ("function", "if"))):
                st.pop()
            else:
                break

    def _top(self):
        return self.stack[-1] if self.stack else None

    # ------------------------------------------------------------------ comentarios
    def _comment(self, t, i):
        same_line = (not t.nl) and bool(self.cur)
        if not same_line:
            if self.pending is not None:
                if self.cur:
                    self.flush()
                if self.pending in ("stmt", "tbl"):
                    self.stmt_start = self.pending == "stmt"
                self.pending = None
            elif self.cur:
                self.flush()
            if t.blank:
                self.blank()
        self.put(t.t, same_line)
        is_line = t.t.startswith("--") and not t.t.startswith("--[")
        nxt = self.toks[i + 1] if i + 1 < self.n else None
        if is_line or (nxt is not None and nxt.nl):
            if self.pending is None:
                self.pending = "cmt"

    # ------------------------------------------------------------------ bucle principal
    def run(self):
        toks, n, stack = self.toks, self.n, self.stack
        for i in range(n):
            t = toks[i]
            k, tx = t.k, t.t

            if i == self.func_hend:
                self.func_hend = -1
                if k == "kw" and tx == "end":
                    stack.append(["FE"])
                else:
                    stack.append(["F"])
                    self.indent += 1
                    self.pending = "stmt"

            if k == "comment":
                self._comment(t, i)
                continue

            pv = self.pv
            self._pop_ifx(k, tx, pv)

            # ---- ¿empieza una sentencia nueva? (solo se decide por la estructura del código)
            brk = False
            if pv is not None and i >= self.func_hend and value_end(pv):
                if k == "name":
                    brk = not self.no_break
                elif k == "kw":
                    if tx in STMT_STARTERS:
                        brk = True
                    elif tx == "do":
                        top = self._top()
                        brk = not (top and top[0] == "LOOP" and top[1] == "cond")
                elif k == "op" and tx == "::":
                    brk = i + 2 < n and toks[i + 1].k == "name" and toks[i + 2].t == "::"

            if self.pending is not None:
                if self.cur:
                    self.flush()
                if self.pending in ("stmt", "tbl"):
                    self.stmt_start = self.pending == "stmt"
                self.pending = None
                if t.blank:
                    self.blank()
                self._function_spacing(i)
            elif brk and self.cur:
                self.flush()
                self.stmt_start = True
                if t.blank:
                    self.blank()
                self._function_spacing(i)
            elif t.nl and self.cur and self._soft_break(t, pv):
                self.flush()
                self.cont = tx not in CLOSERS

            # ---- manejo por tipo de token
            if k == "kw":
                self._keyword(i, t, brk)
            elif k == "op":
                self._operator(i, t)
            else:
                self._emit(t)
                if k == "name":
                    if tx == "export" and i + 1 < n and toks[i + 1].t == "type":
                        self.no_break = 2
                    elif tx == "type" and not self.no_break and i + 2 < n and toks[i + 1].k == "name" and toks[i + 2].t in ("=", "<"):
                        self.no_break = 1

        self.flush()
        while self.lines and self.lines[-1] == "":
            self.lines.pop()
        return "\n".join(self.lines) + "\n"

    def _soft_break(self, t, pv):
        """Respeta un salto de línea del original solo cuando la expresión sigue abierta."""
        if t.k == "kw" and t.t in ("end", "else", "elseif", "until", "then", "do"):
            return False       # estos tokens ya gestionan su propia línea e indentación
        if self.bdepth > 0:
            return True
        if pv is not None and not value_end(pv):
            return True
        if t.k == "op" and (t.t in CONT_OPS or t.t in (".", ":")):
            return True
        if t.k == "kw" and t.t in ("and", "or"):
            return True
        return False

    def _function_spacing(self, i):
        """Línea en blanco antes de funciones de primer nivel."""
        if self.indent != 0 or not self.lines or self.lines[-1] == "":
            return
        t = self.toks[i]
        is_func = t.k == "kw" and (t.t == "function" or (t.t == "local" and i + 1 < self.n and self.toks[i + 1].t == "function"))
        if is_func and not self.lines[-1].lstrip().startswith("--"):
            self.blank()

    # ------------------------------------------------------------------ palabras clave
    def _keyword(self, i, t, brk):
        tx, st = t.t, self.stack
        top = self._top()
        if tx == "end":
            if top and top[0] == "FE":
                st.pop()
                self._emit(t)
            else:
                if top and top[0] in ("IF", "LOOP", "DO", "F"):
                    st.pop()
                    self.indent = max(0, self.indent - 1)
                self.flush()
                self._emit(t)
            nxt = self.toks[i + 1] if i + 1 < self.n else None
            if nxt is not None and not self._end_continues(nxt):
                self.pending = "stmt"
        elif tx == "else":
            if top and top[0] == "IFX":
                top[1] = True
                self._emit(t)
            else:
                self.indent = max(0, self.indent - 1)
                self.flush()
                self._emit(t)
                self.indent += 1
                self.pending = "stmt"
        elif tx == "elseif":
            if top and top[0] == "IFX":
                self._emit(t)
            else:
                self.indent = max(0, self.indent - 1)
                self.flush()
                self._emit(t)
        elif tx == "then":
            self._emit(t)
            if top and top[0] == "IF":
                self.indent += 1
                self.pending = "stmt"
        elif tx == "if":
            is_stmt = self.stmt_start or brk
            st.append(["IF"] if is_stmt else ["IFX", False])
            self._emit(t)
        elif tx in ("while", "for"):
            st.append(["LOOP", "cond"])
            self._emit(t)
        elif tx == "do":
            if top and top[0] == "LOOP" and top[1] == "cond":
                top[1] = "body"
            else:
                st.append(["DO"])
            self._emit(t)
            self.indent += 1
            self.pending = "stmt"
        elif tx == "repeat":
            st.append(["REP"])
            self._emit(t)
            self.indent += 1
            self.pending = "stmt"
        elif tx == "until":
            if top and top[0] == "REP":
                st.pop()
                self.indent = max(0, self.indent - 1)
            self.flush()
            self._emit(t)
        elif tx == "function":
            self._emit(t)
            hend = _header_end(self.toks, i)
            if hend is not None:
                self.func_hend = hend
        else:
            self._emit(t)

    @staticmethod
    def _end_continues(nxt):
        if nxt.k == "op":
            return nxt.t in CLOSERS or nxt.t in (",", ";", ".", ":", "(", "[") or nxt.t in BINOPS
        return nxt.k == "kw" and nxt.t in ("and", "or")

    # ------------------------------------------------------------------ operadores / signos
    def _operator(self, i, t):
        tx, st = t.t, self.stack
        if tx in ("(", "["):
            self._emit(t)
            st.append(["P"])
            self.bdepth += 1
        elif tx in (")", "]"):
            top = self._top()
            if top and top[0] == "P":
                st.pop()
                self.bdepth = max(0, self.bdepth - 1)
            self._emit(t)
        elif tx == "{":
            multi, flat = self.tbl.get(i, (False, True))
            self._emit(t)
            st.append(["T", multi, flat])
            self.bdepth += 1
            if multi:
                self.indent += 1
                self.pending = "tbl"
        elif tx == "}":
            top = self._top()
            if top and top[0] == "T":
                st.pop()
                self.bdepth = max(0, self.bdepth - 1)
                if top[1]:
                    self.indent = max(0, self.indent - 1)
                    self.flush()
            self._emit(t)
        elif tx in (",", ";"):
            top = self._top()
            if top and top[0] == "T":
                self._emit(t)
                if top[1]:
                    if not top[2] or self.line_indent * 4 + self.cur_len >= self.WRAP:
                        self.pending = "tbl"
            elif tx == ";":
                nxt = self.toks[i + 1] if i + 1 < self.n else None
                if nxt is not None and nxt.k == "op" and nxt.t == "(":
                    self._emit(t)          # evita la ambigüedad f()\n(g)()
                    self.pending = "stmt"
            else:
                self._emit(t)
        elif tx == "::":
            self._emit(t)
            if i >= 2 and self.toks[i - 2].t == "::" and self.toks[i - 1].k == "name":
                self.pending = "stmt"      # cierre de una etiqueta ::nombre::
        else:
            self._emit(t)


# ============================================================================
# API DEL FORMATEADOR
# ============================================================================
@dataclass
class FormatResult:
    text: str
    mode: str          # full | basic
    tokens: int = 0
    note: str = ""


def _signature(toks):
    return [(t.k, t.t) for t in toks if t.t != ";"]


def basic_indent(code):
    """Formateo de respaldo por líneas (solo cambia espacios; no toca el contenido)."""
    out, indent = [], 0
    for line in code.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith(("end", "until", "else", "elseif", "}")):
            indent = max(0, indent - 1)
        out.append("    " * indent + s)
        opens = low.endswith(("then", "do", "{", "repeat")) or low.startswith(("function", "local function", "repeat")) and "end" not in low
        if opens or low.startswith(("else", "elseif")):
            indent += 1
    return "\n".join(out) + "\n"


def format_lua(code):
    """Formatea Lua/Luau. Comprueba que los tokens del resultado sean los mismos que los de entrada."""
    try:
        toks = tokenize(code)
    except LexError as e:
        return FormatResult(basic_indent(code), "basic", 0, f"No se pudo leer la sintaxis ({e}); se usó formato básico.")
    if not toks:
        return FormatResult(code, "basic", 0, "El archivo no tiene código.")
    try:
        text = _Formatter(toks).run()
        again = tokenize(text)
        ok = _signature(toks) == _signature(again)
    except Exception as e:           # un fallo del formateador nunca debe tumbar el comando
        logger.warning(f"Formateador falló: {e}")
        ok = False
        text = ""
    if not ok:
        return FormatResult(basic_indent(code), "basic", len(toks), "La verificación de tokens falló; se usó formato básico.")
    return FormatResult(text, "full", len(toks))


def deep_clean_and_fix(code):
    """Limpieza de restos de los motores (solo se aplica a la SALIDA de desofuscadores, nunca en .beautify)."""
    fixed = code.replace("if nil == 1 then", "if 1 == 1 then").replace("elseif nil == 2 then", "elseif 1 == 2 then")
    fixed = re.sub(r"local function\s+fn\d+\s*\(\s*\)\s*end", "-- [Función vacía removida automáticamente]", fixed)
    cleaned = []
    for line in fixed.splitlines():
        if "devirt:" in line or 'error("devirt:' in line or "LPH:" in line or "Prometheus" in line:
            continue
        if line.strip().startswith("--[[") and "corrupted" in line.lower():
            continue
        cleaned.append(line)
    result = "\n".join(cleaned)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", result).strip()


def post_process_engine_output(code):
    """Limpia y formatea lo que devuelve un motor de desofuscación."""
    cleaned = deep_clean_and_fix(code)
    if len(cleaned) > MAX_BEAUTIFY_BYTES:
        return cleaned
    return format_lua(cleaned).text.rstrip("\n")


# ============================================================================
# DETECTOR: identifica el ofuscador leyendo la ESTRUCTURA del código (no banners)
# ============================================================================
@dataclass
class Finding:
    family: str
    name: str
    version: str
    score: float
    evidence: list = field(default_factory=list)
    hint: str = ""          # pista de versión de Luraph ("15.0" / "15.1") si el encabezado sigue ahí


CONFIDENT = 0.5            # a partir de aquí se considera identificado
MISMATCH = 0.7             # a partir de aquí un comando directo rechaza scripts de otro tipo

FAMILY_COMMAND = {
    "luraph": ".luraph",
    "prometheus": ".prometheus",
    "moonsec": ".moonveil",
    "goofy": ".goofy",
}

# --- Luraph v15: VM con árbol de despacho binario, `continue` de Luau y métodos de 1-2 letras (K:A(...))
LUR_TREE = re.compile(r"\b[A-Za-z_]\w*\s*<=\s*\d+\s+then\s+if\s+[A-Za-z_]\w*\s*<=\s*\d+\s+then")
LUR_CONT = re.compile(r"\bcontinue\s*;")
LUR_COLON = re.compile(r"\b[A-Za-z_]\w?:[A-Za-z_]\w?\(")
LUR_SLOTS = re.compile(r"\[\d+\]\s*=\s*(?:bit32|buffer|string|table|math)\.\w+")
LUR_START = re.compile(r"\A\s*(?:--[^\n]*\n\s*)*return\s+setmetatable\s*\(\s*\{")
LUR_LOOP = re.compile(r"while\s+[A-Za-z_]\w*\s+do\s+if\s+[A-Za-z_]\w*\s*<=\s*\d+\s+then")
LUR_HEADER = re.compile(r"Luraph Obfuscator v(\d+)\.(\d+)", re.I)   # solo para elegir v15 / v15.1

# --- MoonSec V3: constantes con prefijo \4\8 y llamadas f(clave,"\52\55...")
MOON_PREFIX = re.compile(r"[\"']\\4\\8")
MOON_CALL = re.compile(r"\(\s*\d+\s*,\s*[\"'](?:\\\d{1,3}){8,}")
MOON_ESC = re.compile(r"(?:\\\d{1,3}){40,}")
LOCAL_FUNC = re.compile(r"\blocal\s+function\b")

# --- Goofyscator V11: tabla envoltorio y strings internos de su runtime
GOOFY_START = re.compile(r"\A\s*(?:--[^\n]*\n\s*)*return\s*\{")
WHILE_TRUE = re.compile(r"while\s+true\s+do")

# --- IronBrew 1: función con decenas de parámetros y tabla numérica enorme
IB_PARAMS = re.compile(r"\breturn\s*\(\s*function\s*\(\s*(?:[A-Za-z_]\w*\s*,\s*){15,}")
IB_NUMTABLE = re.compile(r"\blocal\s+[A-Za-z_]\w*\s*=\s*\{\s*-?\d+(?:\s*,\s*-?\d+){20,}")

# --- banners (encabezados que el propio ofuscador deja en el archivo)
MOON_BANNER = re.compile(r"protected (?:with|using) moonsec v3\b", re.I)
GOOFY_BANNER_ANY = re.compile(r"protected by goofyscator v11 beta-1", re.I)

# --- Prometheus
PROM_WRAP = re.compile(r"\A\s*(?:--[^\n]*\n\s*)*return\s*\(?\s*function\s*\(\s*\.\.\.\s*\)")
PROM_SELECT = re.compile(r"select\s*\(\s*[\"']#[\"']\s*,\s*\.\.\.\s*\)")

# --- despacho genérico por opcodes (cualquier VM)
ELSEIF_CHAIN = re.compile(r"\belseif\s+[A-Za-z_]\w*\s*==\s*\d+\s+then")


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
        if tree >= 20:
            score += 0.30
            ev.append(f"binary dispatch tree ({tree} levels)")
        elif tree >= 4:
            score += 0.15
            ev.append(f"binary dispatch tree ({tree} levels)")
        cont = len(LUR_CONT.findall(s))
        if cont >= 15:
            score += 0.15
            ev.append(f"Luau continue in handlers ({cont})")
        slots = len(LUR_SLOTS.findall(s))
        if slots >= 5:
            score += 0.15
            ev.append(f"indexed library slots ({slots})")
        colon = len(LUR_COLON.findall(s))
        if colon >= 100:
            score += 0.10
            ev.append(f"short method calls ({colon})")
        if LUR_START.match(s[:3000]):
            score += 0.25
            ev.append("return setmetatable({...}) wrapper")
        if LUR_LOOP.search(s):
            score += 0.10
            ev.append("VM loop with opcode compare")
        if score >= 0.4:
            m = LUR_HEADER.search(s[:1000])
            if m and m.group(1) == "15":
                hint = f"15.{m.group(2)}"   # la versión no se distingue por estructura: solo si el encabezado sigue ahí
        return min(score, 1.0), ev, hint

    @staticmethod
    def _moonsec(s):
        score, ev = 0.0, []
        if MOON_PREFIX.search(s):
            score += 0.50
            ev.append("constants with \\4\\8 prefix")
        if MOON_CALL.search(s):
            score += 0.15
            ev.append("f(key, \"\\52\\55...\") constant calls")
        if MOON_ESC.search(s):
            score += 0.15
            ev.append("long decimal-escape strings")
        if len(LOCAL_FUNC.findall(s[:80000])) >= 12:
            score += 0.10
            ev.append("12+ local functions (VM layout)")
        return min(score, 1.0), ev

    @staticmethod
    def _goofy(s):
        score, ev = 0.0, []
        if "limitedstack" in s:
            score += 0.40
            ev.append("runtime string limitedstack")
        if "cannot change environment" in s:
            score += 0.15
            ev.append("runtime message cannot change environment")
        if ("__newindex" in s and "__pairs" in s) or ('"newindex"' in s and '"pairs"' in s):
            score += 0.20
            ev.append("handler builder with __pairs/__newindex")
        if "stack overflow" in s and WHILE_TRUE.search(s):
            score += 0.10
            ev.append("runner with stack overflow + while true")
        if GOOFY_START.match(s[:3000]):
            score += 0.15
            ev.append("return {...} table wrapper")
        return min(score, 1.0), ev

    @staticmethod
    def _ironbrew(s, tree):
        score, ev = 0.0, []
        if IB_PARAMS.search(s):
            score += 0.50
            ev.append("function with 15+ parameters")
        if IB_NUMTABLE.search(s):
            score += 0.30
            ev.append("huge numeric constant table")
        if tree >= 20:
            score += 0.10
            ev.append("binary dispatch tree")
        return min(score, 1.0), ev

    @staticmethod
    def _prometheus(s):
        score, ev = 0.0, []
        marks = s[:4000].lower() + " " + s[-1500:].lower()
        has_mark = "prometheus" in marks or "levno" in marks
        if has_mark:
            score += 0.75
            ev.append("Prometheus watermark")
        if PROM_WRAP.match(s[:3000]):
            score += 0.15
            ev.append("return(function(...) wrapper")
        if len(PROM_SELECT.findall(s)) >= 2:
            score += 0.10
            ev.append("repeated select('#', ...)")
        if not has_mark:
            score = min(score, 0.35)    # sin marca de agua solo hay pistas débiles
        return min(score, 1.0), ev

    @staticmethod
    def _apply_banners(s, findings):
        """Un banner o encabezado del ofuscador es prueba directa: sube la confianza a 95%."""
        by_family = {f.family: f for f in findings}
        head = s[:2000]

        m = LUR_HEADER.search(head)
        if m and m.group(1) == "15":
            f = by_family["luraph"]
            f.hint = f"15.{m.group(2)}"
            f.version = f.hint
            f.name = "Luraph v15.1" if f.hint == "15.1" else "Luraph v15"
            f.score = max(f.score, 0.95)
            f.evidence.insert(0, f"header «Luraph Obfuscator v{f.hint}»")

        if MOON_BANNER.search(head):
            f = by_family["moonsec"]
            f.score = max(f.score, 0.95)
            f.evidence.insert(0, "banner «protected with MoonSec V3»")

        if GOOFY_BANNER_ANY.search(head):
            f = by_family["goofy"]
            f.score = max(f.score, 0.95)
            f.evidence.insert(0, "banner «protected by Goofyscator V11 BETA-1»")
        return findings

    @staticmethod
    def scan(code, use_banners=True):
        """Devuelve la lista de Finding ordenada por puntaje (mayor primero).
        use_banners=False ignora encabezados y mira solo la estructura (para validar salidas)."""
        s = Detector._sample(code)
        findings = []

        l_score, l_ev, l_hint = Detector._luraph(s)
        if l_hint == "15.1":
            l_name, l_ver = "Luraph v15.1", "15.1"
        elif l_hint == "15.0":
            l_name, l_ver = "Luraph v15", "15.0"
        else:
            l_name, l_ver = "Luraph v15", "15.x"
        findings.append(Finding("luraph", l_name, l_ver, l_score, l_ev, l_hint))

        m_score, m_ev = Detector._moonsec(s)
        findings.append(Finding("moonsec", "MoonSec V3", "3", m_score, m_ev))

        g_score, g_ev = Detector._goofy(s)
        findings.append(Finding("goofy", "Goofyscator V11", "11", g_score, g_ev))

        tree = len(LUR_TREE.findall(s))
        i_score, i_ev = Detector._ironbrew(s, tree)
        findings.append(Finding("ironbrew", "IronBrew 1", "1", i_score, i_ev))

        p_score, p_ev = Detector._prometheus(s)
        findings.append(Finding("prometheus", "Prometheus", "Unknown", p_score, p_ev))

        if use_banners:
            findings = Detector._apply_banners(s, findings)
        findings.sort(key=lambda f: f.score, reverse=True)
        return findings


# ============================================================================
# ANÁLISIS TÉCNICO (perfil del script, independiente del ofuscador)
# ============================================================================
API_PATTERNS = [
    ("loadstring/load", re.compile(r"\b(?:loadstring|load)\s*\(")),
    ("getfenv/setfenv", re.compile(r"\b(?:getfenv|setfenv)\b")),
    ("HTTP requests", re.compile(r"\b(?:HttpGet|HttpGetAsync|HttpPost|RequestAsync|http_request|syn\.request)\b")),
    ("executor APIs", re.compile(r"\b(?:getgenv|hookfunction|hookmetamethod|getrawmetatable|setreadonly|identifyexecutor|checkcaller|newcclosure|setclipboard|queue_on_teleport|firesignal|fireclickdetector)\b")),
    ("file access", re.compile(r"\b(?:writefile|readfile|appendfile|delfile|listfiles)\b")),
    ("os/io", re.compile(r"\bos\.(?:execute|getenv|remove|rename)\b|\bio\.(?:open|popen)\b")),
    ("debug library", re.compile(r"\bdebug\.(?:getinfo|traceback|sethook|getlocal)\b")),
    ("string.dump", re.compile(r"\bstring\.dump\b")),
    ("coroutines", re.compile(r"\bcoroutine\.(?:wrap|create|resume)\b")),
    ("bit operations", re.compile(r"\bbit32\.\w+|\bbit\.\w+")),
]
URL_FIND = re.compile(r"https?://[^\s\"'`\\)\]>]+", re.I)
WEBHOOK_RE = re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[\w-]+", re.I)
ROBLOX_RE = re.compile(r"\bgame\s*:\s*GetService\b|\bworkspace\b|\bInstance\.new\b|\bscript\.Parent\b|\bEnum\.\w+")
LUAU_RE = re.compile(r"\btypeof\s*\(|\btask\.(?:wait|spawn|delay)\b|\bbuffer\.\w+|\btable\.(?:freeze|clone)\b")
B64_RE = re.compile(r"[A-Za-z0-9+/=_-]{120,}")
HEX_RE = re.compile(r"[0-9a-fA-F]{64,}")
ESC_DEC = re.compile(r"\\\d{1,3}")
NAME_NUMBERED = re.compile(r"^[A-Za-z_]\d{2,6}$")
NAME_CONFUSABLE = re.compile(r"^[Il1O0_]{4,}$")
NAME_HEX = re.compile(r"^_0x[0-9a-fA-F]{3,}$")
COMMON_GLOBALS = frozenset(
    "string table math game workspace script print pairs ipairs next type typeof tostring tonumber select unpack "
    "pcall xpcall error assert setmetatable getmetatable rawget rawset rawequal rawlen require os io debug coroutine "
    "bit32 bit buffer task utf8 Enum Instance Vector3 CFrame Color3 UDim2 Random loadstring load getfenv setfenv "
    "self _G _ENV shared".split()
)


def shannon_entropy(text):
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def analyze_code(code, raw=b""):
    """Perfil técnico del script. Pensado para ejecutarse en un hilo (puede tardar con archivos grandes)."""
    p = {}
    size = len(raw) if raw else len(code.encode("utf-8", "ignore"))
    lines = code.count("\n") + 1
    line_lengths = [len(x) for x in code.split("\n")] if len(code) < 6_000_000 else [len(code)]
    p["size"] = size
    p["lines"] = lines
    p["max_line"] = max(line_lengths) if line_lengths else 0
    p["avg_line"] = (len(code) / lines) if lines else 0
    p["minified"] = (lines <= 3 and len(code) > 2000) or p["avg_line"] > 300
    p["entropy"] = shannon_entropy(code[:100_000])

    # bytecode / codificación (se mira el contenido original en bytes)
    p["bytecode"] = None
    if raw[:4] == b"\x1bLua":
        p["bytecode"] = {0x51: "Lua 5.1", 0x52: "Lua 5.2", 0x53: "Lua 5.3", 0x54: "Lua 5.4"}.get(raw[4] if len(raw) > 4 else 0, "Lua")
    elif raw[:3] == b"\x1bLJ":
        p["bytecode"] = "LuaJIT"
    bad_utf8 = 0
    if raw:
        sample_raw = raw[:200_000]
        bad_utf8 = len(sample_raw) - len(sample_raw.decode("utf-8", "ignore").encode("utf-8"))
    p["non_utf8"] = bad_utf8 > max(10, len(raw[:200_000]) * 0.01) if raw else False

    sample = Detector._sample(code)
    toks = tokenize(sample[:1_500_000], lenient=True)
    p["tokens"] = len(toks)

    names, strings, ops = [], [], Counter()
    for t in toks:
        if t.k == "name":
            names.append(t.t)
        elif t.k == "str":
            strings.append(t.t)
        elif t.k == "op":
            ops[t.t] += 1
    ids = [n for n in names if n not in COMMON_GLOBALS]
    total_ids = len(ids) or 1
    short = sum(1 for n in ids if len(n) <= 2)
    numbered = sum(1 for n in ids if NAME_NUMBERED.match(n))
    confusable = sum(1 for n in ids if NAME_CONFUSABLE.match(n))
    hexish = sum(1 for n in ids if NAME_HEX.match(n))
    p["ids"] = len(ids)
    p["ids_unique"] = len(set(ids))
    p["short_ratio"] = short / total_ids
    p["numbered_ratio"] = numbered / total_ids
    p["confusable_ratio"] = confusable / total_ids
    p["hex_ratio"] = hexish / total_ids
    p["avg_name_len"] = (sum(len(n) for n in ids) / total_ids) if ids else 0

    esc_strings = sum(1 for s_ in strings if len(ESC_DEC.findall(s_)) >= 6)
    p["strings"] = len(strings)
    p["escaped_strings"] = esc_strings
    p["long_strings"] = sum(1 for s_ in strings if len(s_) >= 200)
    p["b64_strings"] = sum(1 for s_ in strings if B64_RE.search(s_))
    p["hex_strings"] = sum(1 for s_ in strings if HEX_RE.search(s_))

    p["apis"] = [label for label, rx in API_PATTERNS if rx.search(sample)]
    hosts = []
    for u in URL_FIND.findall(sample)[:80]:
        host = (urlparse(u).hostname or "").lower()
        if host and host not in hosts:
            hosts.append(host)
    p["hosts"] = hosts[:5]
    p["webhooks"] = len(WEBHOOK_RE.findall(sample))

    luau_hits = sum(ops.get(o, 0) for o in ("+=", "-=", "*=", "/=", "..=", "%=", "^=", "//=", "->"))
    luau_hits += len(LUAU_RE.findall(sample)) + sum(1 for t in toks if t.k == "str" and t.t.startswith("`"))
    luau_hits += len(re.findall(r"\bcontinue\s*;?\s*(?:end|\n|;)", sample))
    lua53_hits = ops.get("//", 0) + ops.get("<<", 0) + ops.get(">>", 0)
    p["dialect"] = "Luau" if luau_hits else ("Lua 5.3+" if lua53_hits else "Lua 5.1 / Luau compatible")
    if ROBLOX_RE.search(sample):
        p["environment"] = "Roblox"
    elif "executor APIs" in p["apis"]:
        p["environment"] = "Executor"
    else:
        p["environment"] = "Generic Lua"

    p["opcode_chain"] = len(ELSEIF_CHAIN.findall(sample))
    p["dispatch_tree"] = len(LUR_TREE.findall(sample))

    # --- nivel de ofuscación (0-100) con las razones que lo sostienen
    score, reasons = 0, []
    if p["confusable_ratio"] > 0.2:
        score += 25
        reasons.append("confusable names (I, l, O, 0)")
    if p["numbered_ratio"] > 0.25:
        score += 20
        reasons.append("numbered names (v1, v2...)")
    if p["hex_ratio"] > 0.1:
        score += 20
        reasons.append("hex-style names (_0x...)")
    if p["short_ratio"] > 0.55 and p["ids"] > 50:
        score += 20
        reasons.append("mostly 1-2 character names")
    if p["minified"]:
        score += 10
        reasons.append("minified into very long lines")
    if p["escaped_strings"] >= 20:
        score += 15
        reasons.append("strings written as decimal escapes")
    if p["b64_strings"] or p["hex_strings"]:
        score += 15
        reasons.append("encoded payload strings")
    if "loadstring/load" in p["apis"] and p["escaped_strings"]:
        score += 10
        reasons.append("loadstring over encoded data")
    if p["dispatch_tree"] >= 20 or p["opcode_chain"] >= 30:
        score += 35
        reasons.append("virtual-machine dispatch loop")
    if p["entropy"] > 5.3:
        score += 10
        reasons.append("high character entropy")
    if p["bytecode"]:
        score = max(score, 80)
        reasons.append(f"precompiled bytecode ({p['bytecode']})")
    score = min(score, 100)
    p["obf_score"] = score
    p["obf_reasons"] = reasons
    if score < 15:
        p["obf_level"] = "None (readable)"
    elif score < 40:
        p["obf_level"] = "Low"
    elif score < 70:
        p["obf_level"] = "Medium"
    else:
        p["obf_level"] = "High"
    return p


# ============================================================================
# EMBEDS DE ANÁLISIS
# ============================================================================
def build_detect_embed(findings, src):
    top = findings[0]
    link = src.link if src.origin != "code" else "Pasted code"
    if top.score >= CONFIDENT:
        lines = [
            f"Name: {top.name}",
            f"Version: {top.version}",
            f"Confidence: {int(top.score * 100)}%",
        ]
        if not FAMILY_COMMAND.get(top.family):
            lines.append("Status: no deobfuscator available")
        lines += ["", f"Detected Link: {link}"]
        return e_ok(f"DETECTED {top.name.upper()}", "\n".join(lines))

    lines = ["Name: Unknown", f"Confidence: {int(top.score * 100)}%"]
    if top.score >= 0.2:
        lines.append(f"Closest: {top.name} ({int(top.score * 100)}%)")
    lines += ["", f"Detected Link: {link}"]
    return e_err("NOT DETECTED", "\n".join(lines))


def build_analyze_embed(profile, findings, src):
    top = findings[0]
    p = profile
    if p["bytecode"]:
        kind = f"Precompiled bytecode ({p['bytecode']})"
    elif top.score >= CONFIDENT:
        kind = f"{top.name} (v{top.version})"
    else:
        kind = "Unknown / none"
    lines = [
        f"Type: {kind}",
        f"Obfuscation: {p['obf_level']} ({p['obf_score']}/100)",
        f"Dialect: {p['dialect']}",
        f"Environment: {p['environment']}",
        "",
        f"Size: {format_size(p['size'])}",
        f"Lines: {p['lines']:,} (longest {p['max_line']:,} chars)",
        f"Entropy: {p['entropy']:.2f} bits/char",
        f"Names: {int(p['short_ratio'] * 100)}% short, {p['ids_unique']:,} unique",
        f"Strings: {p['strings']:,} ({p['escaped_strings']:,} escaped, {p['long_strings']:,} long)",
    ]
    if p["obf_reasons"]:
        lines += ["", "Signs: " + "; ".join(p["obf_reasons"][:5])]
    notes = []
    if p["apis"]:
        notes.append("APIs: " + ", ".join(p["apis"][:6]))
    if p["hosts"]:
        notes.append("Hosts: " + ", ".join(p["hosts"]))
    if p["webhooks"]:
        notes.append(f"Discord webhooks: {p['webhooks']}")
    if p["non_utf8"]:
        notes.append("File is not valid UTF-8")
    if notes:
        lines += [""] + notes
    return e_ok("SCRIPT ANALYSIS", "\n".join(lines))
# ============================================================================
# MOTORES DE DESOFUSCACIÓN (devuelven el código o lanzan DeobfError)
# ============================================================================
class DeobfError(Exception):
    """La herramienta no pudo desofuscar el script (mensaje corto para el usuario)."""
    diag = ""          # salida completa del proceso, si la hay


class MissingDependency(DeobfError):
    """Falta algo en el servidor (Node, .NET, Java, binarios de Luau, archivos del zip...)."""


async def run_stage(args, deadline, label, cwd=None, check=True):
    """Ejecuta un subproceso respetando un tiempo límite compartido (mata todo el grupo si se pasa)."""
    proc = await asyncio.create_subprocess_exec(
        *[str(a) for a in args],
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name != "nt"),
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
        err = DeobfError(f"{label} falló: {diag[-600:]}")    # la causa suele estar al final
        err.diag = diag
        raise err
    return stdout, stderr


def _same_text(a, b):
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def _node():
    return shutil.which("node") or shutil.which("nodejs")


def explain_moonsec_failure(diag):
    """Convierte el error del backend de MoonSec en un mensaje útil (no un stack trace de .NET)."""
    text = (diag or "").strip()
    m = re.search(r"System\.(\w+Exception)", text)
    if m and m.group(1) in ("NullReferenceException", "IndexOutOfRangeException", "ArgumentOutOfRangeException", "InvalidOperationException"):
        return ("This script does not match the MoonSec V3 layout that the backend supports "
                f"({m.group(1)} while analysing the VM). The file is fine; this build of MoonSec is not supported.")
    if "Unsupported MoonSec key layout" in text:
        return "Unsupported MoonSec key layout: the decryption keys are not in a form the backend handles."
    if "tiempo agotado" in text:
        return "MoonSec took too long and was stopped."
    if "Invalid Lua" in text or "Oversized register" in text:
        return "The recovered bytecode did not pass the Lua 5.1 validation."
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "unknown error")
    return f"MoonSec backend failed: {first[:200]}"


async def engine_luraph151(code, uid, timeout):
    tool = os.path.join(LURAPH_DIR, "v15_tool_attempt_source", "deob.js")
    node_bin = _node()
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
            raise DeobfError("El motor no produjo salida (protecciones pesadas o no es Luraph v15.1).")
        return post_process_engine_output(result_code)
    finally:
        _remove(input_file, output_file, json_path, expected_path)


async def engine_prometheus(code, uid, timeout):
    tool = os.path.join(PROM_DIR, "bin", "pdeobf.js")
    node_bin = _node()
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
            raise DeobfError(f"El motor no produjo salida: {detail[-200:]}")
        return post_process_engine_output(result_code)
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
        try:
            await run_stage([dotnet_bin, MOON_DLL, "-dev", "-i", input_file, "-o", bytecode_file], deadline, "MoonSec")
        except DeobfError as e:
            raise DeobfError(explain_moonsec_failure(e.diag or str(e))) from None
        if not os.path.isfile(bytecode_file):
            raise DeobfError("MoonSec no generó bytecode.")
        with open(bytecode_file, "rb") as f:
            if f.read(5) != b"\x1bLua\x51":
                raise DeobfError("MoonSec no generó bytecode Lua 5.1 válido.")

        # Etapa 2: bytecode -> código fuente con unluac
        try:
            await run_stage([java_bin, "-Xmx512m", "-jar", MOON_JAR, "--nodebug", "-o", output_file, bytecode_file], deadline, "unluac")
        except DeobfError as e:
            raise DeobfError("unluac: " + (e.diag or str(e)).splitlines()[-1][:200] if (e.diag or "").strip() else str(e)) from None
        if not os.path.isfile(output_file):
            raise DeobfError("unluac no generó salida.")
        with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        if not result_code.strip():
            raise DeobfError("unluac produjo una salida vacía.")
        return post_process_engine_output(result_code)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def resolve_tsx():
    """tsx local (engines/obf/node_modules), global, o npx como último recurso."""
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
        missing.append(f"archivos de `{GOOFY_ZIP}` (¿está junto al bot?)")
    if not tsx_cmd:
        missing.append("Node.js + `tsx`")
    for exe in ("luau", "luau-ast"):
        if not os.path.isfile(os.path.join(GOOFY_BIN, exe)):
            missing.append(f"binario Linux `{exe}` en `{GOOFY_BIN}/`")
    if missing:
        raise MissingDependency(", ".join(missing) + ". Solución: ejecuta una vez `bash setup_luau.sh` en el servidor.")

    # El motor exige la primera línea de V11; si el script llega sin ella (ya se identificó por
    # su estructura), se la repone para que la herramienta acepte el archivo.
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
        # cwd = engines/ porque capture.mjs resuelve "deobfuscator/deobf/bin/luau" relativo al cwd.
        stdout, stderr = await run_stage(
            tsx_cmd + [cli, os.path.abspath(input_file), os.path.abspath(analysis_file)],
            deadline, "Goofyscator", cwd=GOOFY_ENGINES, check=False,
        )
        try:
            summary = json.loads(stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise DeobfError("Goofyscator no devolvió resultado: " + stderr.decode("utf-8", "replace")[-250:])
        if not summary.get("ok"):
            raise DeobfError("Goofyscator V11 falló: " + str(summary.get("error", "sin detalles"))[:250])
        if summary.get("artifact_only"):
            raise DeobfError("Recuperación incompleta: " + str(summary.get("status", ""))[:250])

        result_file = os.path.join(work_dir, "deobfuscated.lua")
        if not os.path.isfile(result_file):
            raise DeobfError("Goofyscator no generó deobfuscated.lua")
        with open(result_file, "r", encoding="utf-8", errors="ignore") as f:
            result_code = f.read()
        if not result_code.strip():
            raise DeobfError("Goofyscator produjo una salida vacía.")
        return result_code.strip()    # ya viene validado y formateado por el motor
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _post_json(url, body, timeout):
    """POST JSON con la biblioteca estándar. Devuelve (status, texto)."""
    import urllib.request
    import urllib.error
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


async def decompile_oracle(bytecode, timeout):
    """Manda el bytecode (base64) al descompilador Oracle y devuelve el código Lua."""
    import base64
    body = {"script": base64.b64encode(bytecode).decode("ascii"), "decompilerOptions": {}}
    url = f"{ORACLE_URL}?key={ORACLE_KEY}&version=2"     # la clave nunca se muestra en mensajes
    try:
        status, text = await asyncio.to_thread(_post_json, url, body, max(10, timeout))
    except Exception:
        raise DeobfError("No pude conectar con el descompilador (revisa la conexión o la clave `ORACLE`).")
    if status != 200:
        raise DeobfError(f"El descompilador respondió HTTP {status}: {text[:200]}")
    if not text.strip():
        raise DeobfError("El descompilador devolvió una salida vacía.")
    return text


async def engine_ironbrew2(raw, uid, timeout):
    """raw = bytes del archivo de IronBrew 2 (no texto)."""
    dotnet_bin = shutil.which("dotnet")
    missing = []
    if not dotnet_bin:
        missing.append(".NET 9 runtime (`dotnet`)")
    if not os.path.isfile(IB2_TOOL):
        missing.append(f"archivos de `{IB2_ZIP}` (¿está junto al bot?)")
    if not ORACLE_KEY:
        missing.append("variable de entorno `ORACLE` (clave del descompilador)")
    if missing:
        raise MissingDependency(", ".join(missing))

    name_in = f"ib2_in_{uid}.bin"
    name_out = f"ib2_out_{uid}.luac"
    in_path = os.path.join(IB2_WORK, name_in)
    out_path = os.path.join(IB2_WORK, name_out)
    try:
        with open(in_path, "wb") as f:
            f.write(raw)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        # La herramienta lee y escribe por nombre relativo a su carpeta (igual que el bot original).
        await run_stage([dotnet_bin, os.path.abspath(IB2_TOOL), name_in, name_out], deadline,
                        "IronBrew 2", cwd=IB2_WORK, check=True)
        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            raise DeobfError("El deobfuscador no generó bytecode. ¿Es un archivo válido de IronBrew 2?")
        with open(out_path, "rb") as f:
            bytecode = f.read()
        remaining = max(10, deadline - loop.time())
        code = await decompile_oracle(bytecode, remaining)
        return post_process_engine_output(code)
    finally:
        _remove(in_path, out_path)


ENGINES = {
    "ironbrew2": {"label": "IronBrew 2", "family": "ironbrew2", "fn": engine_ironbrew2, "binary": True,
                  "title": "IRONBREW 2 DEOBFUSCATED", "wait": "Deobfuscando bytecode y descompilando..."},
    "luraph151":  {"label": "Luraph v15.1", "family": "luraph",     "fn": engine_luraph151,  "title": "LURAPH V15.1 DEOBFUSCATED",
                   "wait": "Procesando capas de virtualización..."},
    "prometheus": {"label": "Prometheus",   "family": "prometheus", "fn": engine_prometheus, "title": "PROMETHEUS DEOBFUSCATED",
                   "wait": "Procesando desofuscación..."},
    "moonveil":   {"label": "MoonSec V3",   "family": "moonsec",    "fn": engine_moonveil,   "title": "MOONSEC V3 DEOBFUSCATED",
                   "wait": "Devirtualizando bytecode..."},
    "goofy":      {"label": "Goofyscator",  "family": "goofy",      "fn": engine_goofy,      "title": "GOOFYSCATOR V11 DEOBFUSCATED",
                   "wait": "Recuperando la VM V11..."},
}


def luraph_plan(finding):
    """Orden de los motores de Luraph: v15.1 primero solo si el encabezado lo dice."""
    return ["luraph151"]     # un solo motor para Luraph v15 y v15.1


def validate_result(original, result, family):
    """(True, '') si el resultado parece una desofuscación real; si no, (False, motivo)."""
    if not result or not result.strip():
        return False, "salida vacía"
    if _same_text(result, original):
        return False, "la salida es idéntica a la entrada"
    head = result[:20000]
    bad = sum(1 for ch in head if ch not in "\r\n\t" and (ord(ch) < 32 or ord(ch) == 127))
    if head and bad / len(head) > 0.05:
        return False, "la salida es binaria, no es código Lua"
    if not re.search(r"\b(local|function|end|return|print|if|for|while)\b", result):
        return False, "la salida no parece código Lua"
    top = Detector.scan(result, use_banners=False)[0]
    if top.score >= CONFIDENT and top.family == family:
        return False, f"la salida sigue ofuscada ({top.name})"
    return True, ""


# ============================================================================
# CPU: análisis pesado en hilos, con tope de concurrencia
# ============================================================================
_cpu_sem = None


async def run_cpu(fn, *args):
    global _cpu_sem
    if _cpu_sem is None:
        _cpu_sem = asyncio.Semaphore(3)      # se crea aquí: necesita el event loop en marcha
    async with _cpu_sem:
        return await asyncio.to_thread(fn, *args)


# ============================================================================
# COLA DE TRABAJOS (evita saturar el bot)
# ============================================================================
class QueueRefused(Exception):
    pass


@dataclass(eq=False)
class Job:
    user_id: int
    msg: object
    work: object            # función async sin argumentos
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
        """Motivo de rechazo o None si puede entrar a la cola."""
        if self.user_busy(user_id):
            return "Ya tienes un trabajo en cola o ejecutándose. Espera a que termine."
        if len(self._running) >= self.workers and len(self._waiting) >= self.max_waiting:
            return f"La cola está llena ({self.max_waiting} esperando). Intenta en unos minutos."
        return None

    def stats(self):
        """(procesando, esperando) tal como lo ve el usuario: lo que ya tiene worker libre cuenta como procesando."""
        total = len(self._running) + len(self._waiting)
        running = min(self.workers, total)
        return running, total - running

    def _idle(self):
        return max(0, self.workers - len(self._running))

    def position_if_added(self):
        """Posición que tendría un trabajo nuevo (0 = empieza ya)."""
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
                    STATS["jobs_failed"] += 1
                    await safe_edit(job.msg, e_err("TIMEOUT", "El trabajo tardó demasiado y se canceló."))
                except Exception as e:
                    STATS["jobs_failed"] += 1
                    logger.error(f"Trabajo falló: {e}", exc_info=True)
                    await safe_edit(job.msg, e_err("CRITICAL ERROR", f"```{str(e)[:400]}```"))
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
                    continue          # hay un worker libre: arranca en cuanto lo tome
                if job.last_pos != pos:
                    job.last_pos = pos
                    await safe_edit(job.msg, ui_waiting(pos, *self.stats()))
                    await asyncio.sleep(0.4)     # no pasarse del rate limit de Discord


queue = JobQueue(MAX_CONCURRENT_JOBS, MAX_WAITING_JOBS)


def ui_waiting(position, running, waiting):
    return e_load(f"QUEUED #{position}", f"Processing: {running}\nWaiting: {waiting}\n\nEste mensaje se actualiza solo.")


# ============================================================================
# ENTREGA DEL RESULTADO
# ============================================================================
async def deliver_result(ctx, msg, title, result_code, src, start_time):
    """Embed verde con vista previa; el archivo va en un mensaje aparte debajo."""
    final_text = f"-- Deobfuscado por Lexy Deobf\n\n{result_code}\n"
    path = f"executable_script_{ctx.message.id}.lua"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(final_text)
        output_size = os.path.getsize(path)
        elapsed = time.time() - start_time
        body = (
            "**Output Preview**\n"
            f"```lua\n{make_preview(final_text)}\n```\n"
            f"Source: {src.link}\n"
            f"-# input: {format_size(src.size)} · output: {format_size(output_size)} · took: {elapsed:.1f}s\n\n"
            "**Output File:**"
        )
        try:
            await msg.delete()
        except Exception:
            pass
        await send_embed(ctx, e_ok(title, body))
        await send_file(ctx, path, "executable_script.lua")
    finally:
        _remove(path)


# ============================================================================
# EJECUCIÓN DE UN TRABAJO
# ============================================================================
async def execute_plan(ctx, msg, code, src, plan, detected_label, start_time):
    """Prueba los motores del plan en orden; entrega el primero cuyo resultado pasa la validación."""
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
        await safe_edit(msg, e_load(f"DEOBFUSCATING {spec['label'].upper()}{step}", f"{spec['wait']}\nDetected: {detected_label}"))
        try:
            arg_in = src.raw if spec.get("binary") else code
            result = await spec["fn"](arg_in, uid, min(remaining, 300))
            ok, why = await run_cpu(validate_result, code, result, spec["family"])
        except DeobfError as e:
            failures.append((spec["label"], str(e)))
            continue
        except Exception as e:
            logger.error(f"{spec['label']} lanzó {e}", exc_info=True)
            failures.append((spec["label"], f"error interno: {str(e)[:80]}"))
            continue
        if not ok:
            failures.append((spec["label"], why))
            continue

        # Resultado válido: se entrega y se termina (un fallo al enviar NO debe probar otros motores).
        try:
            await deliver_result(ctx, msg, spec["title"], result, src, start_time)
            STATS["jobs_ok"] += 1
        except Exception as e:
            STATS["jobs_failed"] += 1
            logger.error(f"No se pudo enviar el resultado: {e}", exc_info=True)
            try:
                await send_embed(ctx, e_err("COULD NOT SEND RESULT", f"Se desofuscó con {spec['label']} pero Discord rechazó el envío.\n```{str(e)[:250]}```"))
            except Exception:
                pass
        return

    STATS["jobs_failed"] += 1
    lines = "\n".join(f"{name}: {reason.replace(chr(10), ' ')[:140]}" for name, reason in failures)
    await safe_edit(msg, e_err("DEOBFUSCATION FAILED", f"Detected: {detected_label}\n{lines}"))


async def run_job(ctx, msg, src, mode, key=None, announce=True):
    """mode: 'luraph' (.luraph, elige v15/v15.1) | 'engine' (comando directo, key = motor)."""
    start_time = time.time()
    code = src.text
    if announce:                      # si estaba en cola, el mensaje aún dice "QUEUED"
        await safe_edit(msg, e_load("ANALYZING", "Leyendo la estructura del código..."))
    findings = await run_cpu(Detector.scan, code)
    top = findings[0]
    confident = top.score >= CONFIDENT
    detected_label = f"{top.name} ({int(top.score * 100)}%)" if confident else "unknown"

    if mode == "engine":
        spec = ENGINES[key]
        # Solo se rechaza si el código es claramente de OTRO ofuscador (evita resultados basura).
        if top.score >= MISMATCH and top.family != spec["family"]:
            cmd = FAMILY_COMMAND.get(top.family)
            hint = f"Usa `{cmd}`." if cmd else "No hay desofuscador para ese tipo."
            await safe_edit(msg, e_err("WRONG OBFUSCATOR", f"Este script parece {top.name} ({int(top.score * 100)}%), no {spec['label']}.\n{hint}"))
            return
        await execute_plan(ctx, msg, code, src, [key], detected_label, start_time)
        return

    # mode == 'luraph'
    luraph = next(f for f in findings if f.family == "luraph")
    if top.score >= MISMATCH and top.family != "luraph":
        cmd = FAMILY_COMMAND.get(top.family)
        hint = f"Usa `{cmd}`." if cmd else "No hay desofuscador para ese tipo."
        await safe_edit(msg, e_err("NOT LURAPH", f"Este script parece {top.name} ({int(top.score * 100)}%).\n{hint}"))
        return
    await execute_plan(ctx, msg, code, src, luraph_plan(luraph), detected_label, start_time)


async def start_job(ctx, arg, mode, key=None):
    """Lee el script, valida y lo mete a la cola."""
    refusal = queue.check(ctx.author.id)
    if refusal:
        await send_embed(ctx, e_err("QUEUE", refusal))
        return
    try:
        src = await get_source(ctx, arg)
    except InputError as e:
        await send_embed(ctx, e_err("INVALID INPUT", str(e)[:400]))
        return
    except Exception as e:
        logger.error(f"Error leyendo la entrada: {e}", exc_info=True)
        await send_embed(ctx, e_err("ERROR", f"```{str(e)[:300]}```"))
        return
    if not src.text.strip():
        await send_embed(ctx, e_err("INVALID INPUT", "El archivo está vacío."))
        return

    pos = queue.position_if_added()
    first = e_load("ANALYZING", "Leyendo la estructura del código...") if pos == 0 else ui_waiting(pos, *queue.stats())
    msg = await send_embed(ctx, first)

    async def work():
        await run_job(ctx, msg, src, mode, key, announce=pos > 0)

    job = Job(user_id=ctx.author.id, msg=msg, work=work, last_pos=pos)
    try:
        queue.submit(job)
    except QueueRefused as e:
        await safe_edit(msg, e_err("QUEUE", str(e)))


# ============================================================================
# COMANDOS: información
# ============================================================================
@bot.command(name="ping")
async def cmd_ping(ctx):
    """Prueba de vida: si responde, el bot y los comandos funcionan."""
    raw = getattr(bot, "latency", float("nan"))
    latency = raw * 1000 if raw == raw else 0      # NaN si aún no hay conexión
    await send_embed(ctx, e_ok("PONG", f"Latency: {latency:.0f} ms\nUptime: {format_duration(time.time() - STATS['started'])}"))


@bot.command(name="help")
async def cmd_help(ctx):
    body = (
        "Usa los comandos con un archivo adjunto, una URL, un bloque de código o respondiendo a un mensaje.\n\n"
        "**Deobfuscators**\n"
        "• `.luraph`\n"
        "• `.ironbrew2` (alias `.ib2`)\n"
        "• `.prometheus`\n"
        "• `.moonveil`\n"
        "• `.goofy`\n\n"
        "**Tools**\n"
        "• `.detect` - identifica el ofuscador\n"
        "• `.analyze` - perfil técnico del script\n"
        "• `.beautify` - formatea el código\n"
        "• `.get <url>` - descarga un archivo\n"
        "• `.queue` - estado de la cola\n"
        "• `.list` - desofuscadores disponibles"
    )
    await send_embed(ctx, e_list("COMMANDS", body))


@bot.command(name="list")
async def cmd_list(ctx):
    body = (
        "Lista de deobfuscadores activos:\n\n"
        f"**1. Luraph v15 / v15.1 {EMOJI_LURAPH} **\n"
        "• Comando: `.luraph`\n\n"
        f"**2. Prometheus {EMOJI_PROMETHEUS} **\n"
        "• Comando: `.prometheus`\n\n"
        "**3. MoonSec V3**\n"
        "• Comando: `.moonveil` (alias: `.moonsec`, `.msd`)\n\n"
        "**4. Goofyscator V11**\n"
        "• Comando: `.goofy` (alias: `.goofyscator`, `.gv11d`)\n\n"
        "**5. IronBrew 2**\n"
        "• Comando: `.ironbrew2` (alias: `.ib2`)"
    )
    await send_embed(ctx, e_list("AVAILABLE DEOBFUSCATORS", body))


@bot.command(name="queue")
async def cmd_queue(ctx):
    running, waiting = queue.stats()
    uptime = format_duration(time.time() - STATS["started"])
    body = (
        f"Processing: {running}/{queue.workers}\n"
        f"Waiting: {waiting}/{queue.max_waiting}\n"
        f"Completed: {STATS['jobs_ok']}\n"
        f"Failed: {STATS['jobs_failed']}\n"
        f"Uptime: {uptime}"
    )
    await send_embed(ctx, e_list("QUEUE STATUS", body))


# ============================================================================
# COMANDOS: herramientas
# ============================================================================
@bot.command(name="detect")
@commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.user)
async def cmd_detect(ctx, *, arg: str = None):
    msg = await send_embed(ctx, e_load("ANALYZING", "Leyendo la estructura del código..."))
    try:
        src = await get_source(ctx, arg)
        if not src.text.strip() and not src.raw:
            raise InputError("El archivo está vacío.")
        if src.raw[:4] == b"\x1bLua":
            version = {0x51: "5.1", 0x52: "5.2", 0x53: "5.3", 0x54: "5.4"}.get(src.raw[4] if len(src.raw) > 4 else 0, "Unknown")
            link = src.link if src.origin != "code" else "Pasted code"
            await safe_edit(msg, e_ok("DETECTED LUA BYTECODE", f"Name: Lua bytecode\nVersion: {version}\nConfidence: 100%\n\nDetected Link: {link}"))
            return
        findings = await run_cpu(Detector.scan, src.text)
        await safe_edit(msg, build_detect_embed(findings, src))
    except InputError as e:
        await safe_edit(msg, e_err("INVALID INPUT", str(e)[:400]))
    except Exception as e:
        logger.error(f"Error en .detect: {e}", exc_info=True)
        await safe_edit(msg, e_err("ERROR", f"```{str(e)[:300]}```"))


@bot.command(name="analyze", aliases=["analyse", "info"])
@commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.user)
async def cmd_analyze(ctx, *, arg: str = None):
    msg = await send_embed(ctx, e_load("ANALYZING", "Generando el perfil del script..."))
    try:
        src = await get_source(ctx, arg)
        if not src.text.strip() and not src.raw:
            raise InputError("El archivo está vacío.")
        profile = await run_cpu(analyze_code, src.text, src.raw)
        findings = await run_cpu(Detector.scan, src.text)
        await safe_edit(msg, build_analyze_embed(profile, findings, src))
    except InputError as e:
        await safe_edit(msg, e_err("INVALID INPUT", str(e)[:400]))
    except Exception as e:
        logger.error(f"Error en .analyze: {e}", exc_info=True)
        await safe_edit(msg, e_err("ERROR", f"```{str(e)[:300]}```"))


@bot.command(name="get")
@commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.user)
async def cmd_get(ctx, *, arg: str = None):
    msg = await send_embed(ctx, e_load("FETCHING", "Descargando..."))
    path = f"fetched_{ctx.message.id}.lua"
    try:
        parsed = parse_arg(arg)
        if not parsed or parsed[0] != "url":
            raise InputError("Proporciona una URL válida.")
        url = normalize_url(parsed[1])
        raw, final_url = await http_fetch(url, MAX_INPUT_BYTES)
        with open(path, "wb") as f:
            f.write(raw)
        try:
            await msg.delete()
        except Exception:
            pass
        await send_embed(ctx, e_ok("SUCCESSFULLY FETCHED", f"Fetched:\n{final_url}\n\nDownload Fetched File:"))
        await send_file(ctx, path, "contenido.lua")
    except InputError as e:
        await safe_edit(msg, e_err("FETCH FAILED", str(e)[:400]))
    except Exception as e:
        logger.error(f"Error en .get: {e}", exc_info=True)
        await safe_edit(msg, e_err("FETCH FAILED", f"```{str(e)[:300]}```"))
    finally:
        _remove(path)


@bot.command(name="beautify")
@commands.cooldown(1, COMMAND_COOLDOWN, commands.BucketType.user)
async def cmd_beautify(ctx, *, arg: str = None):
    start_time = time.time()
    msg = await send_embed(ctx, e_load("FORMATTING", "Formateando el código..."))
    path = f"beautify_{ctx.message.id}.lua"
    try:
        src = await get_source(ctx, arg)
        if not src.text.strip():
            raise InputError("El archivo está vacío.")
        if src.size > MAX_BEAUTIFY_BYTES:
            raise InputError(f"El archivo pesa {format_size(src.size)}; para formatear el máximo es {format_size(MAX_BEAUTIFY_BYTES)}.")
        result = await run_cpu(format_lua, src.text)

        with open(path, "w", encoding="utf-8") as f:
            f.write(result.text)
        lines_before = src.text.count("\n") + 1
        lines_after = result.text.count("\n")
        check = "tokens identical" if result.mode == "full" else "basic formatting only"
        body = (
            f"Time: {format_duration(time.time() - start_time)}\n"
            f"Lines: {lines_before:,} → {lines_after:,}\n"
            f"Size: {format_size(src.size)} → {format_size(os.path.getsize(path))}\n"
            f"Check: {check}"
        )
        if result.note:
            body += f"\nNote: {result.note}"
        body += "\n\nDownload Beautified File:"
        try:
            await msg.delete()
        except Exception:
            pass
        await send_embed(ctx, e_ok("SUCCESSFULLY BEAUTIFIED", body))
        await send_file(ctx, path, "beautified.lua")
    except InputError as e:
        await safe_edit(msg, e_err("INVALID INPUT", str(e)[:400]))
    except Exception as e:
        logger.error(f"Error en .beautify: {e}", exc_info=True)
        await safe_edit(msg, e_err("ERROR", f"```{str(e)[:300]}```"))
    finally:
        _remove(path)


# ============================================================================
# COMANDOS: desofuscadores (todos pasan por la cola)
# ============================================================================
@bot.command(name="luraph")
async def cmd_luraph(ctx, *, arg: str = None):
    await start_job(ctx, arg, "luraph")


@bot.command(name="luraph151")
async def cmd_luraph151(ctx, *, arg: str = None):
    await start_job(ctx, arg, "engine", "luraph151")


@bot.command(name="ironbrew2", aliases=["ib2"])
async def cmd_ironbrew2(ctx, *, arg: str = None):
    await start_job(ctx, arg, "engine", "ironbrew2")


@bot.command(name="prometheus")
async def cmd_prometheus(ctx, *, arg: str = None):
    await start_job(ctx, arg, "engine", "prometheus")


@bot.command(name="moonveil", aliases=["moonsec", "msd"])
async def cmd_moonveil(ctx, *, arg: str = None):
    await start_job(ctx, arg, "engine", "moonveil")


@bot.command(name="goofy", aliases=["goofyscator", "gv11d"])
async def cmd_goofy(ctx, *, arg: str = None):
    await start_job(ctx, arg, "engine", "goofy")


# ============================================================================
# INICIO DEL BOT
# ============================================================================
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        logger.critical("¡Falta la variable de entorno DISCORD_TOKEN!")
    else:
        bot.run(TOKEN)
