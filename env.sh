# Source this file: `source env.sh` — puts project-local toolchains on PATH.
QSX_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export QSX_ROOT
export PATH="$QSX_ROOT/.venv/bin:$QSX_ROOT/.tools/oss-cad-suite/bin:$QSX_ROOT/.tools/jdk/Contents/Home/bin:$PATH"
if [ -f "$QSX_ROOT/.tools/emsdk/emsdk_env.sh" ]; then
  EMSDK_QUIET=1 . "$QSX_ROOT/.tools/emsdk/emsdk_env.sh" >/dev/null 2>&1
fi
export TLA2TOOLS="$QSX_ROOT/.tools/tla2tools.jar"
