// Bit-packed syndrome (Stim b8 layout: detector v at bit v%8 of byte v/8) -> sparse defect list.
// Three implementations with identical output (ascending indices < V):
//   naive : one test per detector bit (what a straightforward harness does)
//   word  : 64-bit words, count-trailing-zeros + clear-lowest-bit
//   simd  : 16-byte blocks; all-zero blocks are skipped with one vector test (Wasm SIMD128 / NEON),
//           non-zero blocks fall back to the word loop. Falls back to `word` without SIMD support.
#pragma once
#include <cstdint>
#include <cstring>

#if defined(__wasm_simd128__)
#include <wasm_simd128.h>
#define QSX_HAVE_SIMD 1
#elif defined(__ARM_NEON) && !defined(QSX_NO_NEON)
#include <arm_neon.h>
#define QSX_HAVE_SIMD 1
#else
#define QSX_HAVE_SIMD 0
#endif

namespace qsx {

inline int unpack_naive(const uint8_t* bits, int V, int* out) {
  int n = 0;
  for (int v = 0; v < V; v++)
    if ((bits[v >> 3] >> (v & 7)) & 1) out[n++] = v;
  return n;
}

inline int unpack_word_tail(const uint8_t* bits, int from_byte, int nbytes, int V, int n, int* out) {
  int i = from_byte;
  for (; i + 8 <= nbytes; i += 8) {
    uint64_t w;
    std::memcpy(&w, bits + i, 8);
    while (w) {
      int v = (i << 3) + __builtin_ctzll(w);
      if (v < V) out[n++] = v;
      w &= w - 1;
    }
  }
  for (; i < nbytes; i++) {
    uint32_t w = bits[i];
    while (w) {
      int v = (i << 3) + __builtin_ctz(w);
      if (v < V) out[n++] = v;
      w &= w - 1;
    }
  }
  return n;
}

inline int unpack_word(const uint8_t* bits, int V, int* out) {
  return unpack_word_tail(bits, 0, (V + 7) >> 3, V, 0, out);
}

inline int unpack_simd(const uint8_t* bits, int V, int* out) {
#if QSX_HAVE_SIMD
  const int nbytes = (V + 7) >> 3;
  int n = 0, i = 0;
  for (; i + 16 <= nbytes; i += 16) {
#if defined(__wasm_simd128__)
    v128_t x = wasm_v128_load(bits + i);
    if (!wasm_v128_any_true(x)) continue;
#else
    uint8x16_t x = vld1q_u8(bits + i);
    if (vmaxvq_u8(x) == 0) continue;
#endif
    for (int h = 0; h < 16; h += 8) {
      uint64_t w;
      std::memcpy(&w, bits + i + h, 8);
      while (w) {
        int v = ((i + h) << 3) + __builtin_ctzll(w);
        if (v < V) out[n++] = v;
        w &= w - 1;
      }
    }
  }
  return unpack_word_tail(bits, i, nbytes, V, n, out);
#else
  return unpack_word(bits, V, out);
#endif
}

}  // namespace qsx
