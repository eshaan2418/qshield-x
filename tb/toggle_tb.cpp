// Switching-activity proxy for the QSX-UF core (BLOCKERS B3: no vendor power estimator in the open flow).
// Built with Verilator --coverage-toggle; drives rtl/qsx_uf_core.sv with Stim-sampled syndromes (no
// golden-model check here: bit-exactness is established by core_tb) and writes the toggle-coverage database.
// bench/m2_hw.py sums the per-bit toggle counts. The result is an activity estimate, not Watts.
//   toggle_tb --graph g.qsxg --stim dets.b8 [--max-shots N] --cov out.dat
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <string>
#include <type_traits>
#include <vector>

#include "Vqsx_uf_core.h"
#include "qsx/decoder.hpp"
#include "verilated.h"
#include "verilated_cov.h"

#ifndef QSX_TB
#error "QSX_TB (threshold bits) must be defined"
#endif

template <typename T>
static void set_bit(T& s, int b, bool v) {
  if constexpr (std::is_integral_v<T>) {
    if (v) s |= (T(1) << b);
    else s &= ~(T(1) << b);
  } else {
    if (v) s[b >> 5] |= (1u << (b & 31));
    else s[b >> 5] &= ~(1u << (b & 31));
  }
}

int main(int argc, char** argv) {
  auto ctx = std::make_unique<VerilatedContext>();
  std::string graph, stim, cov = "coverage.dat";
  long max_shots = -1;
  for (int i = 1; i + 1 < argc; i += 2) {
    std::string k = argv[i], v = argv[i + 1];
    if (k == "--graph") graph = v;
    else if (k == "--stim") stim = v;
    else if (k == "--max-shots") max_shots = std::atol(v.c_str());
    else if (k == "--cov") cov = v;
  }
  qsx::Graph g = qsx::Graph::load(graph);
  auto* top = new Vqsx_uf_core{ctx.get()};
  for (int e = 0; e < g.E; e++)
    for (int b = 0; b < QSX_TB; b++) set_bit(top->thr_in, e * QSX_TB + b, (g.thr[e] >> b) & 1);
  top->max_rounds = 255;
  top->cycle_budget = 0;
  unsigned long long cycles = 0;
  auto tick = [&]() {
    top->clk = 0;
    top->eval();
    top->clk = 1;
    top->eval();
    cycles++;
  };
  top->rst_n = 0;
  top->start = 0;
  tick();
  tick();
  top->rst_n = 1;
  tick();
  // Exclude reset/configuration activity: count only decode activity.
  ctx->coveragep()->zero();
  const unsigned long long c0 = cycles;

  std::ifstream f(stim, std::ios::binary);
  std::vector<uint8_t> D((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
  const int db = (g.V + 7) / 8;
  long n = 0;
  unsigned long long busy = 0;
  for (size_t s = 0; s + db <= D.size() && (max_shots < 0 || n < max_shots); s += db, n++) {
    for (int v = 0; v < g.V; v++) set_bit(top->defect_in, v, (D[s + (v >> 3)] >> (v & 7)) & 1);
    top->start = 1;
    tick();
    top->start = 0;
    while (!top->done) tick();
    busy += top->cycles;
    tick();  // DONE -> IDLE
  }
  ctx->coveragep()->write(cov.c_str());
  std::printf("{\"graph\":\"%s\",\"shots\":%ld,\"cycles\":%llu,\"busy_cycles\":%llu}\n", graph.c_str(), n,
              cycles - c0, busy);
  delete top;
  return 0;
}
