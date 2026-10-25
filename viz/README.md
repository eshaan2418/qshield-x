# QShield-X browser view (M9)

```
make viz          # export datasets (bench/viz_data.py) and serve the repo at http://127.0.0.1:8765/viz/
make viz-test     # headless-Chrome smoke test (viz/smoke.mjs): decode, seek to a failure, verify signed results
```

* Stim-sampled shots (d = 3, 5, 7; p = 0.001, 0.003, 0.006) decoded live by the Wasm SIMD build of the QSX-UF decoder
  (`wasm/qsx_api.cpp`: `qsx_decode_one`, `qsx_hw_cycles`). Every detector time layer gets its own panel. It shows
  detection events, space-like/boundary corrections, time-like corrections (rings), and space-time diagonals (dashed).
* Statistics: running P_L with a 95% Wilson interval, the browser's decode time, and RTL core cycles from the
  cycle-exact model for any LANES/PIPE choice. The RTL latency estimate uses the best place-and-route Fmax in
  `results/M2/report.json`, and is labelled as such.
* "Verify & replay" checks the Ed25519 signature of the end-to-end demo manifest (WebCrypto) and the SHA-256 of every
  artefact. It then replays the syndrome trace through Wasm and compares the result with the committed
  hardware/fallback predictions.
* Hover tooltips on detectors, chart crosshair and histogram bars. Table view for the current shot. Light/dark themes.
