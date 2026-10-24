// Reduced case: v128.any_true feeding br_if (the zero-block skip in qsx::unpack_simd).
d8.file.execute('test/mjsunit/wasm/wasm-module-builder.js');
const builder = new WasmModuleBuilder();
builder.addMemory(1, 1);
// (func (param $p i32) (result i32)  ;; returns 1 if 16 bytes at p are all zero
builder.addFunction('skip', kSig_i_i).addBody([
  kExprBlock, kWasmVoid,
    kExprLocalGet, 0,
    kSimdPrefix, kExprS128LoadMem, 0, 0,
    kSimdPrefix, kExprV128AnyTrue,
    kExprBrIf, 0,
    kExprI32Const, 1,
    kExprReturn,
  kExprEnd,
  kExprI32Const, 0,
]).exportFunc();
// select variant, and ctz loop for comparison
builder.addFunction('ctzloop', kSig_i_l).addLocals(kWasmI32, 1).addBody([
  kExprLoop, kWasmVoid,
    kExprLocalGet, 0, kExprI64Eqz, kExprBrIf, 1 - 1 + 0,  // placeholder replaced below
  kExprEnd, kExprLocalGet, 1]).exportFunc();
const inst = builder.instantiate();
for (let i = 0; i < 10; i++) inst.exports.skip(0);
print(inst.exports.skip(0));
