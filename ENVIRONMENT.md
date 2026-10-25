# ENVIRONMENT (probed 2026-10-24)

## Host
- Apple M5 Pro, 18 cores (arm64), 48 GB RAM, 788 GB free disk; macOS 27.0.1 (Darwin 27.0.0)
- Xcode at /Applications/Xcode.app (full SDK available)

## Toolchain (project-local, `source env.sh`)
| Tool | Version | Source |
|------|---------|--------|
| Verilator | 5.053 devel (v5.052-567) | OSS CAD Suite 2026-10-24 (`.tools/oss-cad-suite`) |
| Yosys (+ slang plugin) | 0.70+219 | OSS CAD Suite |
| nextpnr-ecp5 (Project Trellis) | 0.11.1-79 | OSS CAD Suite |
| SymbiYosys, yosys-smtbmc | bundled | OSS CAD Suite |
| Z3 / Bitwuzla / Yices | 5.1.0 / 0.9.1 / 2.7.0 | OSS CAD Suite / pip z3-solver 5.1.0 |
| Java | OpenJDK 21.0.13 (Temurin) | `.tools/jdk` |
| TLA+ tools (TLC) | 2.19 (tla2tools.jar, release v1.7.4, sha256 936a2620…) | `.tools/tla2tools.jar` |
| Emscripten | 6.0.13 | `.tools/emsdk` |
| Node.js | v24.19.0 | bundled with emsdk |
| Apple clang | 21.0.0 | Xcode |
| Python | 3.12.14 (`.venv`) | stim 1.16.0, pymatching 2.4.0, sinter 1.16.0, numpy 2.5.4, scipy 1.18.1, torch 2.14.1, cryptography 50.0.2, z3-solver 5.1.0, cocotb 2.1.0 |
| PyMatching C++ | v2.4.0 (libpymatching, built from source) | `.tools/src/pymatching` |
| Google Chrome | 155.0.8059.85 | /Applications |
| Docker | 29.7.2 (daemon up) | system |
| tectonic (paper build) | 0.17.0 | Homebrew |
| d8 (V8 15.8, built from source) | rev in build/v8_rev.txt | v8/src/v8/out/rel |

Not available: Vivado, Quartus, any FPGA board, vendor power estimators, cmake (installed via pip into .venv).

## Fallback rungs chosen (M0)
| Capability | Rung used |
|---|---|
| FPGA measurement | No board -> post-PnR timing/utilisation + cycle-accurate Verilator latency |
| Synthesis/PnR | Yosys + nextpnr-ecp5, LFE5U-85F CABGA381 speed 8 |
| Power/energy | Toggle-count proxy from simulation (labelled estimate) |
| Engine work | Standalone V8 + d8 build from source attempted (disk/RAM sufficient); Chromium build not attempted (V8 path chosen first per M5) |
| CI | Workflow defined; executed locally (`make ci`), see BLOCKERS B1 |

## Timer resolution
`std::chrono::steady_clock` on this host advances in 41.67 ns steps (24 MHz timebase); CPU latency
percentiles below ~100 ns are quantised accordingly.
