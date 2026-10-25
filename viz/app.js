// QShield-X browser view (M9). Serve the repo root over HTTP (e.g. `python -m http.server`) and open /viz/.
// Everything shown is computed in the page: Wasm decoding of Stim-sampled shots, cycle-exact RTL cycles, running P_L,
// and verification of the signed end-to-end demo artefacts.
'use strict';
(async function () {
  const $ = (id) => document.getElementById(id);
  const css = (v) => getComputedStyle($('root')).getPropertyValue(v).trim();
  const SVGNS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  };
  const tip = $('tip');
  const showTip = (ev, html) => {
    tip.innerHTML = html; tip.style.display = 'block';
    tip.style.left = (ev.clientX + 14) + 'px'; tip.style.top = (ev.clientY + 12) + 'px';
  };
  const hideTip = () => { tip.style.display = 'none'; };
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const fmt = (x, d = 0) => x.toLocaleString(undefined, {maximumFractionDigits: d, minimumFractionDigits: d});
  const STATUS = ['OK', 'TIMEOUT', 'PARITY_ERROR', 'WATCHDOG', 'FRAME_ERROR', 'CFG_INVALID'];

  function wilson(k, n) {
    if (!n) return [0, 1];
    const z = 1.959964, ph = k / n, den = 1 + z * z / n;
    const c = (ph + z * z / (2 * n)) / den, h = z * Math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den;
    return [Math.max(0, c - h), Math.min(1, c + h)];
  }

  // ------------------------------------------------------------------ Wasm module
  async function newDecoder(graphText) {
    const M = await QSXModule({locateFile: (f) => '../wasm/dist/' + f, print: () => {}, printErr: () => {}});
    const enc = new Uint8Array(graphText.length + 1);
    for (let i = 0; i < graphText.length; i++) enc[i] = graphText.charCodeAt(i) & 0x7f;
    const gp = M._qsx_malloc(enc.length);
    M.HEAPU8.set(enc, gp);
    const V = M._qsx_init(gp);
    if (V <= 0) throw new Error('qsx_init failed');
    const E = M._qsx_num_edges();
    const eu = new Int32Array(E), ev = new Int32Array(E);
    for (let e = 0; e < E; e++) { eu[e] = M._qsx_edge_u(e); ev[e] = M._qsx_edge_v(e); }
    const rb = (V + 7) >> 3;
    const rowp = M._qsx_malloc(rb), edgep = M._qsx_malloc(4 * E), infop = M._qsx_malloc(16);
    return {
      M, V, E, eu, ev, rb,
      decode(row) {
        M.HEAPU8.set(row, rowp);
        const n = M._qsx_decode_one(rowp, edgep, E, infop);
        const info = new Int32Array(M.HEAPU8.buffer, infop, 3);
        return {edges: Array.from(new Int32Array(M.HEAPU8.buffer, edgep, n)), status: info[0], obs: info[1],
                rounds: info[2]};
      },
      cycles(row, lanes, pipe) { M.HEAPU8.set(row, rowp); return M._qsx_hw_cycles(rowp, lanes, pipe); },
      timeBatch(rows, n) {  // median-free throughput: one clock read per batch (timer resolution is coarse)
        const t0 = performance.now();
        for (let i = 0; i < n; i++) { M.HEAPU8.set(rows[i], rowp); M._qsx_decode_one(rowp, edgep, E, infop); }
        return (performance.now() - t0) * 1e6 / n;
      },
    };
  }

  // ------------------------------------------------------------------ state
  const index = await (await fetch('data/index.json')).json();
  const sel = $('set');
  for (const s of index.sets) {
    const o = document.createElement('option');
    o.value = s.name; o.textContent = `d=${s.d}, p=${s.p}`;
    if (s.name === 'd5_p0.003') o.selected = true;
    sel.appendChild(o);
  }
  let S = null, playing = false, wasmNs = [];

  async function load(name) {
    playing = false; $('play').textContent = 'Play';
    const doc = await (await fetch(`data/${name}.json`)).json();
    const graph = await (await fetch(`data/${doc.graph}`)).text();
    const dec = await newDecoder(graph);
    const dets = b64(doc.dets_b64), obs = b64(doc.obs_b64);
    const rows = [];
    for (let s = 0; s < doc.shots; s++) rows.push(dets.subarray(s * doc.row_bytes, (s + 1) * doc.row_bytes));
    S = {doc, dec, rows, obs, i: 0, fails: 0, hist: [], cyc: [], name};
    wasmNs = [];
    for (let k = 0; k < 5; k++) wasmNs.push(dec.timeBatch(rows, Math.min(500, rows.length)));
    $('tSet').textContent = `d=${doc.d}, p=${doc.p}, ${doc.V} detectors, ${dec.E} graph edges`;
    layout();
    step(1);
  }

  // ------------------------------------------------------------------ lattice
  let panels = [];
  function layout() {
    const box = $('layers');
    box.innerHTML = '';
    panels = [];
    const C = S.doc.coords;
    const ts = [...new Set(C.map((c) => c[2]))].sort((a, b) => a - b);
    const xs = C.map((c) => c[0]), ys = C.map((c) => c[1]);
    const x0 = Math.min(...xs) - 1.5, x1 = Math.max(...xs) + 1.5, y0 = Math.min(...ys) - 1.5, y1 = Math.max(...ys) + 1.5;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const size = S.doc.d <= 3 ? 150 : S.doc.d <= 5 ? 170 : 190;
    const sc = size / Math.max(x1 - x0, y1 - y0);
    S.geo = {cx, cy, sc, x0, y0};
    for (const t of ts) {
      const div = document.createElement('div');
      div.className = 'layer';
      div.innerHTML = `<div class="t">t = ${t}</div>`;
      const svg = el('svg', {width: (x1 - x0) * sc, height: (y1 - y0) * sc});
      div.appendChild(svg);
      box.appendChild(div);
      const gE = el('g', {}, svg), gN = el('g', {}, svg);
      panels.push({t, svg, gE, gN});
    }
    S.nodeEls = [];
    for (let v = 0; v < S.doc.V; v++) {
      const [x, y, t] = C[v];
      const p = panels.find((q) => q.t === t);
      const c = el('circle', {cx: (x - x0) * sc, cy: (y - y0) * sc, r: Math.max(3, sc * 0.28)}, p.gN);
      c.addEventListener('mousemove', (ev) => {
        const r = S.cur;
        const inc = r ? r.res.edges.filter((e) => S.dec.eu[e] === v || S.dec.ev[e] === v).length : 0;
        showTip(ev, `<b>detector ${v}</b><br>x=${x}, y=${y}, t=${t}<br>${r && r.defect[v] ? 'detection event' : 'quiet'}` +
          `<br>${inc} corrected incident edge(s)`);
      });
      c.addEventListener('mouseleave', hideTip);
      S.nodeEls.push(c);
    }
  }

  function draw(row, res) {
    const {sc, x0, y0, cx, cy} = S.geo;
    const C = S.doc.coords, V = S.doc.V;
    const defect = new Uint8Array(V);
    for (let v = 0; v < V; v++) defect[v] = (row[v >> 3] >> (v & 7)) & 1;
    S.cur = {row, res, defect};
    for (const p of panels) p.gE.innerHTML = '';
    const P = (v) => [(C[v][0] - x0) * sc, (C[v][1] - y0) * sc];
    const panelOf = (v) => panels.find((q) => q.t === C[v][2]);
    const ring = new Uint8Array(V);
    const corr = css('--series-2');
    for (const e of res.edges) {
      const u = S.dec.eu[e], w = S.dec.ev[e];
      if (w === V) {  // boundary edge: stub away from the centre
        const [px, py] = P(u);
        let dx = C[u][0] - cx, dy = C[u][1] - cy;
        const L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
        el('line', {x1: px, y1: py, x2: px + dx * sc * 1.3, y2: py + dy * sc * 1.3, stroke: corr, 'stroke-width': 2.5,
                    'stroke-linecap': 'round'}, panelOf(u).gE);
        continue;
      }
      const sameT = C[u][2] === C[w][2], sameXY = C[u][0] === C[w][0] && C[u][1] === C[w][1];
      if (sameT) {
        const [ax, ay] = P(u), [bx, by] = P(w);
        el('line', {x1: ax, y1: ay, x2: bx, y2: by, stroke: corr, 'stroke-width': 2.5, 'stroke-linecap': 'round'},
           panelOf(u).gE);
      } else if (sameXY) {
        ring[u] = ring[w] = 1;
      } else {  // space-time diagonal: dashed segment in both layers
        for (const [a, b] of [[u, w], [w, u]]) {
          const [ax, ay] = P(a), [bx, by] = P(b);
          el('line', {x1: ax, y1: ay, x2: bx, y2: by, stroke: corr, 'stroke-width': 2, 'stroke-dasharray': '3 3'},
             panelOf(a).gE);
        }
      }
    }
    for (let v = 0; v < V; v++) {
      const c = S.nodeEls[v];
      c.setAttribute('fill', defect[v] ? css('--series-1') : css('--node'));
      c.setAttribute('stroke', ring[v] ? corr : css('--surface-1'));
      c.setAttribute('stroke-width', ring[v] ? 2.5 : 1.5);
    }
    if (!$('tableCard').hidden) table(defect, res);
  }

  function table(defect, res) {
    const ds = [];
    for (let v = 0; v < S.doc.V; v++) if (defect[v]) ds.push(v);
    const rows = res.edges.map((e) => {
      const u = S.dec.eu[e], w = S.dec.ev[e];
      return `<tr><td>${e}</td><td>${u}</td><td>${w === S.doc.V ? 'boundary' : w}</td></tr>`;
    }).join('');
    $('tableView').innerHTML = `<p class="note">Detection events (${ds.length}): ${ds.join(', ') || 'none'}</p>` +
      `<table><thead><tr><th>corrected edge</th><th>u</th><th>v</th></tr></thead><tbody>${rows ||
      '<tr><td colspan=3>no correction</td></tr>'}</tbody></table>`;
  }

  // ------------------------------------------------------------------ decode loop + stats
  function lanes() { const v = $('lanes').value; return v === 'V' ? S.dec.V : Number(v); }

  // Advance until `want(row, res, failed)` holds for the shot just decoded (or the dataset ends).
  function seek(want) {
    playing = false; $('play').textContent = 'Play';
    while (S.i < S.rows.length) {
      step(1, true);
      if (want(S.cur.row, S.cur.res, S.cur.failed)) break;
    }
    step(0);
  }

  function step(n, quiet) {
    let last = null;
    if (n === 0 && S.cur) last = {row: S.cur.row, res: S.cur.res, pred: S.cur.pred, truth: S.cur.truth};
    for (let k = 0; k < n && S.i < S.rows.length; k++) {
      const row = S.rows[S.i];
      const res = S.dec.decode(row);
      const truth = S.obs[S.i] & 1;
      const pred = res.status === 0 ? res.obs & 1 : -1;
      if (pred !== truth) S.fails++;
      S.i++;
      const [lo, hi] = wilson(S.fails, S.i);
      S.hist.push([S.i, S.fails / S.i, lo, hi]);
      S.cyc.push(S.dec.cycles(row, lanes(), Number($('pipe').value)));
      last = {row, res, pred, truth};
    }
    if (!last) { playing = false; $('play').textContent = 'Play'; return; }
    if (quiet) {  // seek: only record the decoded shot, render once at the end
      S.cur = {row: last.row, res: last.res, failed: last.pred !== last.truth, pred: last.pred, truth: last.truth};
      return;
    }
    draw(last.row, last.res);
    S.cur.pred = last.pred; S.cur.truth = last.truth; S.cur.failed = last.pred !== last.truth;
    const [lo, hi] = wilson(S.fails, S.i);
    $('shotTitle').textContent = `Shot ${S.i} of ${S.rows.length}: predicted ${last.pred < 0 ? 'error' : last.pred}, ` +
      `true ${last.truth}, ${last.pred === last.truth ? 'correct' : 'LOGICAL FAILURE'}`;
    $('tShots').textContent = fmt(S.i);
    $('tFail').textContent = fmt(S.fails);
    $('tPl').textContent = `P_L ${(S.fails / S.i).toExponential(2)} [${lo.toExponential(1)}, ${hi.toExponential(1)}]`;
    const w = [...wasmNs].sort((a, b) => a - b)[2];
    $('tWasm').textContent = fmt(w);
    const cyc = S.cyc[S.cyc.length - 1];
    $('tCyc').textContent = fmt(cyc);
    $('tCycS').textContent = `LANES=${lanes()}, PIPE=${$('pipe').value}, cycle-exact model`;
    const fm = index.fmax[String(S.doc.d)];
    if (fm) {
      $('tNs').textContent = fmt(cyc * 1e3 / fm.fmax_mhz) + ' ns';
      $('tNsS').textContent = `core cycles / ${fm.fmax_mhz.toFixed(1)} MHz (best PnR, ${fm.tag}); excl. shell + I/O`;
    } else {
      $('tNs').textContent = 'n/a';
      $('tNsS').textContent = `no PnR result fits the device at d=${S.doc.d}`;
    }
    $('tRounds').textContent = last.res.rounds;
    $('tStatus').innerHTML = `<span class="${last.res.status === 0 ? 'status-ok' : 'status-bad'}">${STATUS[last.res.status]}</span>`;
    plChart();
    histChart();
  }

  function plChart() {
    const svg = $('plChart');
    svg.innerHTML = '';
    const W = svg.clientWidth || 600, H = 190, m = {l: 54, r: 10, t: 8, b: 24};
    const pts = S.hist.filter((_, k) => k % Math.max(1, Math.floor(S.hist.length / 400)) === 0 || k === S.hist.length - 1);
    const ymax = Math.max(1e-4, ...pts.slice(Math.floor(pts.length / 10)).map((p) => p[3])) * 1.1;
    const X = (n) => m.l + (W - m.l - m.r) * (n / S.rows.length), Y = (v) => H - m.b - (H - m.t - m.b) * Math.min(1, v / ymax);
    for (let k = 0; k <= 4; k++) {
      const v = ymax * k / 4;
      el('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: css('--border')}, svg);
      el('text', {x: m.l - 6, y: Y(v) + 3, 'text-anchor': 'end'}, svg).textContent = v.toExponential(1);
    }
    el('text', {x: W - m.r, y: H - 6, 'text-anchor': 'end'}, svg).textContent = `shots (of ${fmt(S.rows.length)})`;
    if (pts.length < 2) return;
    const band = pts.map((p) => `${X(p[0])},${Y(p[3])}`).concat(pts.slice().reverse().map((p) => `${X(p[0])},${Y(p[2])}`));
    el('polygon', {points: band.join(' '), fill: css('--series-1'), opacity: 0.15}, svg);
    el('polyline', {points: pts.map((p) => `${X(p[0])},${Y(p[1])}`).join(' '), fill: 'none', stroke: css('--series-1'),
                    'stroke-width': 2}, svg);
    const cross = el('line', {y1: m.t, y2: H - m.b, stroke: css('--text-muted'), 'stroke-dasharray': '2 3', opacity: 0}, svg);
    const hit = el('rect', {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent'}, svg);
    hit.addEventListener('mousemove', (ev) => {
      const r = svg.getBoundingClientRect();
      const n = Math.round((ev.clientX - r.left - m.l) / (W - m.l - m.r) * S.rows.length);
      const p = S.hist[Math.max(0, Math.min(S.hist.length - 1, n - 1))];
      cross.setAttribute('x1', X(p[0])); cross.setAttribute('x2', X(p[0])); cross.setAttribute('opacity', 1);
      showTip(ev, `after ${fmt(p[0])} shots<br>P_L ${p[1].toExponential(2)}<br>95% CI [${p[2].toExponential(2)}, ` +
        `${p[3].toExponential(2)}]`);
    });
    hit.addEventListener('mouseleave', () => { cross.setAttribute('opacity', 0); hideTip(); });
  }

  function histChart() {
    const svg = $('hist');
    svg.innerHTML = '';
    const W = svg.clientWidth || 330, H = 150, m = {l: 34, r: 8, t: 6, b: 22};
    const c = S.cyc, mx = Math.max(...c), nb = 24, bw = Math.max(1, Math.ceil((mx + 1) / nb));
    const bins = new Array(Math.ceil((mx + 1) / bw)).fill(0);
    for (const x of c) bins[Math.floor(x / bw)]++;
    const bmax = Math.max(...bins);
    const bwPx = (W - m.l - m.r) / bins.length;
    bins.forEach((b, k) => {
      const h = (H - m.t - m.b) * b / bmax;
      const r = el('rect', {x: m.l + k * bwPx + 1, y: H - m.b - h, width: Math.max(1, bwPx - 2), height: h, rx: 2,
                            fill: css('--series-3')}, svg);
      r.addEventListener('mousemove', (ev) => showTip(ev, `${k * bw}–${(k + 1) * bw - 1} cycles<br>${b} shots`));
      r.addEventListener('mouseleave', hideTip);
    });
    const s = [...c].sort((a, b) => a - b), q = (f) => s[Math.min(s.length - 1, Math.floor(f * s.length))];
    el('text', {x: m.l, y: H - 6}, svg).textContent = '0';
    el('text', {x: W - m.r, y: H - 6, 'text-anchor': 'end'}, svg).textContent =
      `core cycles → max ${mx} · p50 ${q(0.5)} · p99 ${q(0.99)} (n=${c.length})`;
  }

  // ------------------------------------------------------------------ signed-result verification + replay
  function canonical(o) {
    if (Array.isArray(o)) return '[' + o.map(canonical).join(',') + ']';
    if (o && typeof o === 'object') return '{' + Object.keys(o).sort().map((k) => JSON.stringify(k) + ':' + canonical(o[k])).join(',') + '}';
    return JSON.stringify(o);
  }
  const hex = (buf) => [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, '0')).join('');

  async function verify() {
    const out = $('verifyOut');
    const lines = [];
    const log = (ok, msg) => { lines.push(`<div class="${ok ? 'status-ok' : 'status-bad'}">${msg}</div>`); out.innerHTML = lines.join(''); };
    try {
      const env = await (await fetch('data/e2e/manifest.json')).json();
      const pk = await (await fetch('data/e2e/pubkey.json')).json();
      if (env.kid !== pk.kid) return log(false, 'manifest key id is not the trusted key');
      const key = await crypto.subtle.importKey('raw', b64(pk.ed25519_raw_b64), {name: 'Ed25519'}, false, ['verify']);
      const ok = await crypto.subtle.verify({name: 'Ed25519'}, key, b64(env.sig), new TextEncoder().encode(canonical(env.payload)));
      log(ok, `Ed25519 signature ${ok ? 'valid' : 'INVALID'} (key ${env.kid})`);
      if (!ok) return;
      const files = {};
      for (const f of env.payload.files) {
        const buf = await (await fetch('data/e2e/' + f.name)).arrayBuffer();
        const h = hex(await crypto.subtle.digest('SHA-256', buf));
        const good = h === f.sha256 && buf.byteLength === f.size;
        log(good, `${f.name}: ${buf.byteLength} bytes, sha256 ${good ? 'matches' : 'MISMATCH'}`);
        if (!good) return;
        files[f.name] = new Uint8Array(buf);
      }
      const dec = await newDecoder(new TextDecoder().decode(files[pk.graph]));
      const trace = files['trace.b8'], committed = files['committed_predictions.u8'];
      let match = 0;
      const n = committed.length;
      for (let s = 0; s < n; s++) {
        const r = dec.decode(trace.subarray(s * dec.rb, (s + 1) * dec.rb));
        if ((r.status === 0 ? r.obs & 0xff : 0xff) === committed[s]) match++;
      }
      log(match === n, `Wasm replay reproduces ${match} / ${n} committed predictions`);
      const sum = JSON.parse(new TextDecoder().decode(files['summary.json']));
      lines.push(`<p class="note">${sum.hw_committed} rounds committed from the RTL accelerator, ${sum.sw_committed} from the ` +
        `verified software fallback (d=${sum.d}, p=${sum.p}).</p>`);
      out.innerHTML = lines.join('');
    } catch (e) {
      log(false, 'verification failed: ' + e);
    }
  }

  // ------------------------------------------------------------------ wiring
  function loop() {
    if (!playing) return;
    step(Number($('speed').value));
    requestAnimationFrame(loop);
  }
  $('play').onclick = () => { playing = !playing; $('play').textContent = playing ? 'Pause' : 'Play'; if (playing) loop(); };
  $('step').onclick = () => step(1);
  $('nextDef').onclick = () => seek((row) => row.some((b) => b !== 0));
  $('nextFail').onclick = () => seek((row, res, failed) => failed);
  $('speed').oninput = () => { $('speedv').textContent = $('speed').value; };
  $('set').onchange = () => load(sel.value);
  $('lanes').onchange = $('pipe').onchange = () => { S.cyc = []; for (let k = 0; k < S.i; k++) S.cyc.push(S.dec.cycles(S.rows[k], lanes(), Number($('pipe').value))); histChart(); };
  $('tableBtn').onclick = () => { $('tableCard').hidden = !$('tableCard').hidden; if (S.cur) draw(S.cur.row, S.cur.res); };
  $('themeBtn').onclick = () => {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    r.dataset.theme = dark ? 'light' : 'dark';
    if (S.cur) { draw(S.cur.row, S.cur.res); plChart(); histChart(); }
  };
  $('verifyBtn').onclick = verify;
  await load(sel.value);
})();
