# Results index

Every experiment: command, output files, one-line finding. All JSON files carry a `provenance` block
(git commit, tool versions, seed, config, UTC timestamp).

| Milestone | Experiment | Command | Output | Finding |
|-----------|------------|---------|--------|---------|
| M1 | Weight-quantisation pilot | `python bench/m1_baselines.py --distances 5,7 --ps 0.003,0.006 --weights unweighted,q1..q8m15` | `results/M1/pilot_weights/` | q5 best 3-bit option (DECISIONS D5) |
| M1 | P_L sweep d=3..9, p=1e-3..1e-2 | `python bench/m1_baselines.py --weights unweighted,q5 --max-shots 4000000 --target-errors 300` | `results/M1/pl/*.json`, `figs/pl_vs_p.png`, `figs/pl_ratio.png` | QSX-UF-q5 P_L within ~1.1-1.6x of PyMatching; crossings in `summary.json` |
| M1 | CPU latency (1 thread) | `python bench/m1_latency.py` | `results/M1/latency.json`, `figs/cpu_latency_p99.png` | PyMatching and QSX-UF have similar CPU latency; timer resolution ~41.7 ns |
| M1 | Summary/thresholds | `python bench/m1_plots.py` | `results/M1/summary.json` | threshold crossings per decoder |
