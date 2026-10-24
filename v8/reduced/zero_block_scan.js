// Reduced benchmark for the zero-block skip loop of qsx::unpack_simd (QShield-X M5):
//   for each 16-byte block: if (!v128.any_true(load(block))) continue; else count++
// Usage: d8 zero_block_scan.js -- <nonzero_block_fraction> <seed>
// Prints {"ns_per_block": ..., "count": ...} (best of 25 timed passes after a forced tier-up).
d8.file.execute('v8/src/v8/test/mjsunit/wasm/wasm-module-builder.js');

const kBlocks = 4096;  // 64 KiB
const builder = new WasmModuleBuilder();
builder.addMemory(1, 1);
builder.exportMemoryAs('mem');
builder.addFunction('count_nonzero_blocks', kSig_i_i)
    .addLocals(kWasmI32, 2)  // i, count
    .addBody([
      kExprBlock, kWasmVoid,
        kExprLoop, kWasmVoid,
          kExprLocalGet, 1, kExprLocalGet, 0, kExprI32GeU, kExprBrIf, 1,
          kExprBlock, kWasmVoid,
            kExprLocalGet, 1, kExprI32Const, 4, kExprI32Shl,
            kSimdPrefix, kExprS128LoadMem, 0, 0,
            kSimdPrefix, kExprV128AnyTrue, kExprI32Eqz, kExprBrIf, 0,
            kExprLocalGet, 2, kExprI32Const, 1, kExprI32Add, kExprLocalSet, 2,
          kExprEnd,
          kExprLocalGet, 1, kExprI32Const, 1, kExprI32Add, kExprLocalSet, 1,
          kExprBr, 0,
        kExprEnd,
      kExprEnd,
      kExprLocalGet, 2,
    ]).exportFunc();

const frac = Number(arguments[0] || 0);
let seed = Number(arguments[1] || 1) >>> 0;
const rand = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296);
const inst = builder.instantiate();
const mem = new Uint8Array(inst.exports.mem.buffer);
let expected = 0;
for (let b = 0; b < kBlocks; b++) {
  if (rand() < frac) {
    mem[b * 16 + Math.floor(rand() * 16)] = 1 << Math.floor(rand() * 8);
    expected++;
  }
}
const f = inst.exports.count_nonzero_blocks;
for (let i = 0; i < 200; i++) f(kBlocks);  // warm up (dynamic tier-up to the optimizing tier)
const kReps = 200;
let best = Infinity;
for (let t = 0; t < 25; t++) {
  const t0 = performance.now();
  let c = 0;
  for (let i = 0; i < kReps; i++) c += f(kBlocks);
  const dt = performance.now() - t0;
  if (c !== expected * kReps) throw new Error('wrong count ' + c + ' vs ' + expected * kReps);
  best = Math.min(best, dt);
}
print(JSON.stringify({ns_per_block: best * 1e6 / (kReps * kBlocks), count: expected}));
