#!/usr/bin/env bash
# Installs the pinned CI toolchain into .tools/ and .venv/ (the layout env.sh expects). Linux x64/arm64.
set -euo pipefail
cd "$(dirname "$0")/.."
OSS_CAD_DATE=2026-10-24
case "$(uname -m)" in x86_64) ARCH=x64 ;; aarch64) ARCH=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
mkdir -p .tools
if [ ! -x .tools/oss-cad-suite/bin/yosys ]; then
  curl -sSL "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_CAD_DATE}/oss-cad-suite-linux-${ARCH}-${OSS_CAD_DATE//-/}.tgz" \
    | tar -xz -C .tools
fi
if [ ! -f .tools/tla2tools.jar ]; then
  curl -sSL -o .tools/tla2tools.jar https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar
  echo "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88  .tools/tla2tools.jar" | sha256sum -c -
fi
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  # CI targets need neither torch/opacus (M6/M7) nor cocotb.
  grep -v -E '^(torch|opacus|cocotb)==' requirements.txt > .venv/ci-requirements.txt
  .venv/bin/pip install -q -r .venv/ci-requirements.txt
fi
