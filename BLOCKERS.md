# BLOCKERS

| ID | Date | Blocker | Fallback used | Impact on claims |
|----|------|---------|---------------|------------------|
| B1 | 2026-10-24 | No git remote / hosted CI configured; pushing is outward-facing and not done autonomously. | `.github/workflows/ci.yml` defined; identical steps executed locally by `make ci`, logs in `results/ci/`. | "CI green" means the local `make ci` run, not a hosted runner. |
| B2 | 2026-10-24 | No FPGA board; no Vivado/Quartus licence. | Yosys + nextpnr-ecp5 (LFE5U-85F); Verilator cycle counts for latency. | No on-board measurements. All hardware numbers are labelled sim/synth/pnr. |
| B3 | 2026-10-24 | No vendor power estimator for ECP5 in the open flow. | Toggle-count activity proxy from Verilator simulation. | Energy numbers are relative estimates only, not Watts. |
