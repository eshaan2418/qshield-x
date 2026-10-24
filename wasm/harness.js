// QSX-UF WebAssembly benchmark harness. Runs in d8 (V8 shell), Node.js and Chrome.
//   d8:   d8 [flags] wasm/harness.js -- <module.js> <module.wasm> <graph.qsxg> <dets.b8> [obs.b8] [label]
//   node: node wasm/harness.js <module.js> <module.wasm> <graph.qsxg> <dets.b8> [obs.b8] [label]
//   browser: bench/m4_chrome.mjs loads this file and calls globalThis.qsxRun(env)
'use strict';
(function () {
  const isD8 = typeof readbuffer === 'function' && typeof print === 'function' && typeof window === 'undefined'
      && typeof process === 'undefined';
  const isNode = typeof process !== 'undefined' && process.versions && process.versions.node;
  const now = () => performance.now();

  function timerResolutionMs() {
    let best = Infinity;
    for (let i = 0; i < 2000; i++) {
      const a = now();
      let b = now();
      while (b === a) b = now();
      best = Math.min(best, b - a);
    }
    return best;
  }

  function stats(arr) {
    const s = Float64Array.from(arr).sort();
    const q = (f) => s[Math.min(s.length - 1, Math.floor(f * s.length))];
    return {p50: q(0.5), p90: q(0.9), p99: q(0.99), p999: q(0.999), max: s[s.length - 1]};
  }

  async function run(env) {
    // env: {factory, wasmBytes, graphText, dets(Uint8Array), obs(Uint8Array|null), label}
    const out = {label: env.label, engine: isD8 ? 'd8' : isNode ? 'node ' + process.version : 'browser'};
    out.timer_resolution_ms = timerResolutionMs();
    const t0 = now();
    const mod = new WebAssembly.Module(env.wasmBytes);  // synchronous compile (Liftoff by default)
    out.compile_ms = now() - t0;
    let instMs = 0;
    const M = await env.factory({
      instantiateWasm(imports, ok) {
        const t1 = now();
        const inst = new WebAssembly.Instance(mod, imports);
        instMs = now() - t1;
        ok(inst, mod);
        return inst.exports;
      },
      print: () => {}, printErr: () => {},
    });
    out.instantiate_ms = instMs;
    const enc = new TextEncoder().encode(env.graphText + '\0');
    const gp = M._qsx_malloc(enc.length);
    M.HEAPU8.set(enc, gp);
    const V = M._qsx_init(gp);
    const rb = (V + 7) >> 3, shots = Math.floor(env.dets.length / rb);
    const dp = M._qsx_malloc(env.dets.length);
    M.HEAPU8.set(env.dets, dp);
    const pp = M._qsx_malloc(shots);
    const lp = M._qsx_malloc(8 * shots);
    out.V = V; out.shots = shots; out.simd = M._qsx_has_simd();
    const variant = env.variant === undefined ? 2 : env.variant;
    out.variant = variant;
    // Warm-up curve: first 40 calls of 500 shots each (cold code tiers up during this phase).
    const wb = Math.min(500, shots);
    out.warmup_ns_per_shot = [];
    for (let i = 0; i < 40; i++) out.warmup_ns_per_shot.push(M._qsx_bench(dp, wb, 1, variant) / wb);
    // Correctness pass (+ per-shot latency inside wasm, timer = performance.now via emscripten_get_now)
    const bad = M._qsx_decode_batch(dp, shots, pp, lp, variant);
    out.bad_status = bad;
    out.hash = (M._qsx_hash_hi() >>> 0).toString(16).padStart(8, '0') + (M._qsx_hash_lo() >>> 0).toString(16).padStart(8, '0');
    const lat = new Float64Array(M.HEAPF64.buffer, lp, shots);
    out.lat_ns = stats(lat);
    if (env.obs) {
      const pred = M.HEAPU8.subarray(pp, pp + shots);
      let e = 0;
      for (let s = 0; s < shots; s++) e += (pred[s] & 1) !== (env.obs[s] & 1);
      out.errors = e;
    }
    // Steady state: best of 5 full passes; unpack kernel alone, all three variants.
    let best = Infinity;
    for (let r = 0; r < 5; r++) best = Math.min(best, M._qsx_bench(dp, shots, 1, variant));
    out.steady_ns_per_shot = best / shots;
    out.unpack_ns_per_shot = {};
    for (const v of [0, 1, 2]) {
      let ub = Infinity;
      for (let r = 0; r < 5; r++) ub = Math.min(ub, M._qsx_bench_unpack(dp, shots, 1, v));
      out.unpack_ns_per_shot[['naive', 'word', 'simd'][v]] = ub / shots;
    }
    return out;
  }
  globalThis.qsxRun = run;

  async function cli(args) {
    const [modJs, modWasm, graph, dets, obs, label, variant] = args;
    let factory, wasmBytes, graphText, D, O = null;
    if (isD8) {
      load(modJs);
      factory = globalThis.QSXModule;
      wasmBytes = new Uint8Array(readbuffer(modWasm));
      graphText = read(graph);
      D = new Uint8Array(readbuffer(dets));
      if (obs && obs !== '-') O = new Uint8Array(readbuffer(obs));
    } else {
      const fs = require('fs');
      factory = require(require('path').resolve(modJs));
      wasmBytes = new Uint8Array(fs.readFileSync(modWasm));
      graphText = fs.readFileSync(graph, 'utf8');
      D = new Uint8Array(fs.readFileSync(dets));
      if (obs && obs !== '-') O = new Uint8Array(fs.readFileSync(obs));
    }
    const r = await run({factory, wasmBytes, graphText, dets: D, obs: O, label: label || 'wasm',
                         variant: variant === undefined ? 2 : Number(variant)});
    (isD8 ? print : console.log)(JSON.stringify(r));
  }
  if (isD8 && typeof arguments !== 'undefined' && arguments.length) cli(Array.from(arguments));
  else if (isNode && require.main === module) cli(process.argv.slice(2));
})();
