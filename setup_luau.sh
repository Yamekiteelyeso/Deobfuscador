#!/usr/bin/env bash
# Compila luau (parcheado) y luau-ast desde el repo oficial de Luau y los deja donde los usan
# el motor de Luraph v15 y el de Goofyscator. Se ejecuta UNA vez en el servidor Linux.
#
#   bash setup_luau.sh
#
# Requiere: git, cmake, g++, python3 e internet. Tarda unos minutos.
set -euo pipefail

TAG="0.739"                                   # misma versión que build_luau.py
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

for tool in git cmake g++ python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[!] Falta '$tool'. Instálalo (p. ej.: sudo apt install git cmake g++ python3) y vuelve a ejecutar."
        exit 1
    fi
done

# 1) Si el zip de Luraph v15 todavía no está descomprimido, lo hacemos aquí.
if [ ! -d Deobfuscator ]; then
    if [ -f luraphv15.zip ]; then
        echo "[*] Descomprimiendo luraphv15.zip"
        python3 -c "import zipfile; zipfile.ZipFile('luraphv15.zip').extractall('.')"
    else
        echo "[!] No encuentro Deobfuscator/ ni luraphv15.zip junto a este script."
        exit 1
    fi
fi
LURAPH_BIN="Deobfuscator/deobf/bin"
mkdir -p "$LURAPH_BIN"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# 2) Descargar Luau en la versión fija.
echo "[*] Descargando Luau $TAG"
git clone -q --depth 1 --branch "$TAG" https://github.com/luau-lang/luau.git "$WORK/luau"

# 3) Aplicar el mismo parche que usa build_luau.py (el vector metatable queda escribible).
echo "[*] Aplicando parche"
python3 -c "import sys; sys.path.insert(0, '$LURAPH_BIN/..'); import build_luau as b; b.patch('$WORK/luau')"

# 4) Compilar luau (Repl) y luau-ast (Ast.CLI), estáticos para no depender de librerías.
echo "[*] Compilando (puede tardar varios minutos)"
cmake -S "$WORK/luau" -B "$WORK/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLUAU_BUILD_TESTS=OFF \
    -DLUAU_STATIC_CRT=ON \
    -DCMAKE_C_COMPILER=gcc \
    -DCMAKE_CXX_COMPILER=g++ \
    -DCMAKE_C_FLAGS_RELEASE="-O3 -DNDEBUG" \
    -DCMAKE_CXX_FLAGS_RELEASE="-O3 -DNDEBUG" \
    -DCMAKE_EXE_LINKER_FLAGS="-static"
cmake --build "$WORK/build" --config Release --target Luau.Repl.CLI Luau.Ast.CLI --parallel

find_bin() {
    find "$WORK/build" -type f \( -name "$1" -o -name "$2" \) -perm -u+x | head -n 1
}
LUAU_EXE="$(find_bin luau Luau.Repl.CLI)"
AST_EXE="$(find_bin luau-ast Luau.Ast.CLI)"
if [ -z "$LUAU_EXE" ] || [ -z "$AST_EXE" ]; then
    echo "[!] No encontré los binarios compilados. Revisa la salida de cmake arriba."
    exit 1
fi

# 5) Copiar a Luraph v15 y, si existe, a Goofyscator (usan los mismos binarios).
install_to() {
    mkdir -p "$1"
    cp "$LUAU_EXE" "$1/luau"
    cp "$AST_EXE" "$1/luau-ast"
    chmod 755 "$1/luau" "$1/luau-ast"
    echo "[+] Instalado en $1"
}
install_to "$LURAPH_BIN"
if [ -d goofyscator-deobf/engines ]; then
    install_to "goofyscator-deobf/engines/deobfuscator/deobf/bin"
fi

# 6) Comprobación rápida.
"$LURAPH_BIN/luau" --version 2>/dev/null || echo "[!] luau no responde; revisa la compilación."
"$LURAPH_BIN/luau-ast" --help >/dev/null 2>&1 || true
echo "[OK] Listo. Reinicia el bot."
