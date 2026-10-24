// Replay a syndrome trace through the Wasm build of the QSX-UF decoder and print a digest of the predictions.
//   node wasm/replay.js <module.js> <module.wasm> <graph.qsxg> <dets.b8>
// Output: {"shots", "bad_status", "pred_sha256"} where pred is one byte per shot (observable 0/1, 0xff = non-OK).
// Used by bench/e2e_demo.py to check that an inspector reproduces the signed, committed predictions.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

async function main() {
  const [modJs, modWasm, graph, dets] = process.argv.slice(2);
  const factory = require(path.resolve(modJs));
  const wasmBytes = fs.readFileSync(modWasm);
  const M = await factory({wasmBinary: wasmBytes, print: () => {}, printErr: () => {}});
  const text = fs.readFileSync(graph, 'latin1');
  const enc = Buffer.from(text + '\0', 'latin1');
  const gp = M._qsx_malloc(enc.length);
  M.HEAPU8.set(enc, gp);
  const V = M._qsx_init(gp);
  if (V <= 0) throw new Error('qsx_init failed: ' + V);
  const D = fs.readFileSync(dets);
  const rb = (V + 7) >> 3, shots = Math.floor(D.length / rb);
  const dp = M._qsx_malloc(D.length);
  M.HEAPU8.set(D, dp);
  const pp = M._qsx_malloc(shots);
  const lp = M._qsx_malloc(8 * shots);
  const bad = M._qsx_decode_batch(dp, shots, pp, lp, 1);
  const pred = Buffer.from(M.HEAPU8.subarray(pp, pp + shots));
  console.log(JSON.stringify({shots, bad_status: bad,
                              pred_sha256: crypto.createHash('sha256').update(pred).digest('hex')}));
}
main().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
