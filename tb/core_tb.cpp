// Verilator co-simulation: rtl/qsx_uf_core.sv vs qsx::HwModel (bit-exact correction, status, rounds
// and cycle-exact latency).
//   core_tb --graph g.qsxg --lanes P --random N [--seed S] [--stim dets.b8] [--max-rounds R]
//           [--budget B] [--json out.json]
// Random syndromes draw an i.i.d. Bernoulli density per shot from a fixed set (0..0.9).
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <random>
#include <string>
#include <type_traits>
#include <vector>

#include "Vqsx_uf_core.h"
#include "qsx/decoder.hpp"
#include "verilated.h"

#ifndef QSX_TB
#error "QSX_TB (threshold bits) must be defined"
#endif

using namespace qsx;

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
template <typename T>
static bool get_bit(const T& s, int b) {
  if constexpr (std::is_integral_v<T>) return (s >> b) & 1;
  else return (s[b >> 5] >> (b & 31)) & 1;
}

struct Stats {
  long n = 0, mismatches = 0, ok = 0, timeout = 0, watchdog = 0, parity = 0;
  unsigned long long cycles_sum = 0, cycles_max = 0;
};

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  std::string graph, stim, json;
  int lanes = 8, max_rounds = 255;
  long nrand = 0;
  unsigned long budget = 0;
  unsigned long long seed = 1;
  for (int i = 1; i + 1 < argc; i += 2) {
    std::string k = argv[i], v = argv[i + 1];
    if (k == "--graph") graph = v;
    else if (k == "--lanes") lanes = std::atoi(v.c_str());
    else if (k == "--random") nrand = std::atol(v.c_str());
    else if (k == "--seed") seed = std::strtoull(v.c_str(), nullptr, 10);
    else if (k == "--stim") stim = v;
    else if (k == "--max-rounds") max_rounds = std::atoi(v.c_str());
    else if (k == "--budget") budget = std::strtoul(v.c_str(), nullptr, 10);
    else if (k == "--json") json = v;
  }
  Graph g = Graph::load(graph);
  HwModel model(g, HwParams{lanes, max_rounds, static_cast<uint32_t>(budget)});
  auto* top = new Vqsx_uf_core;
  for (int e = 0; e < g.E; e++)
    for (int b = 0; b < QSX_TB; b++) set_bit(top->thr_in, e * QSX_TB + b, (g.thr[e] >> b) & 1);
  top->max_rounds = max_rounds;
  top->cycle_budget = budget;
  auto tick = [&]() {
    top->clk = 0;
    top->eval();
    top->clk = 1;
    top->eval();
  };
  top->rst_n = 0;
  top->start = 0;
  tick();
  tick();
  top->rst_n = 1;
  tick();

  Stats st;
  std::vector<uint8_t> defect(g.V);
  auto run_one = [&](const char* src, long idx) {
    for (int v = 0; v < g.V; v++) set_bit(top->defect_in, v, defect[v]);
    top->start = 1;
    tick();
    top->start = 0;
    long guard = 0;
    while (!top->done) {
      tick();
      if (++guard > 100000000L) {
        std::fprintf(stderr, "hang\n");
        std::exit(3);
      }
    }
    HwResult m = model.decode(defect.data());
    bool bad = top->status != m.status || top->rounds != static_cast<unsigned>(m.rounds & 0xff) ||
               top->cycles != m.cycles || top->obs != static_cast<bool>(m.obs & 1);
    std::vector<uint8_t> mc(g.E, 0);
    for (int e : m.corr) mc[e] = 1;
    for (int e = 0; e < g.E && !bad; e++) bad |= get_bit(top->corr, e) != static_cast<bool>(mc[e]);
    st.n++;
    if (bad) {
      if (st.mismatches < 10)
        std::fprintf(stderr, "MISMATCH %s #%ld: rtl status=%d rounds=%d cycles=%llu | model status=%d rounds=%d cycles=%llu\n",
                     src, idx, top->status, top->rounds, (unsigned long long)top->cycles, m.status, m.rounds,
                     (unsigned long long)m.cycles);
      st.mismatches++;
    }
    switch (m.status) {
      case OK: st.ok++; break;
      case TIMEOUT: st.timeout++; break;
      case WATCHDOG: st.watchdog++; break;
      default: st.parity++;
    }
    st.cycles_sum += m.cycles;
    if (m.cycles > st.cycles_max) st.cycles_max = m.cycles;
    tick();  // DONE -> IDLE
  };

  std::mt19937_64 rng(seed);
  const double dens[] = {0.0, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 0.5, 0.9};
  for (long s = 0; s < nrand; s++) {
    std::bernoulli_distribution b(dens[s % 9]);
    for (int v = 0; v < g.V; v++) defect[v] = b(rng);
    run_one("random", s);
  }
  long nstim = 0;
  if (!stim.empty()) {
    std::ifstream f(stim, std::ios::binary);
    std::vector<uint8_t> D((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    const int db = (g.V + 7) / 8;
    for (size_t s = 0; s + db <= D.size(); s += db, nstim++) {
      for (int v = 0; v < g.V; v++) defect[v] = (D[s + (v >> 3)] >> (v & 7)) & 1;
      run_one("stim", nstim);
    }
  }
  char buf[512];
  std::snprintf(buf, sizeof buf,
                "{\"graph\":\"%s\",\"lanes\":%d,\"random\":%ld,\"stim\":%ld,\"seed\":%llu,\"mismatches\":%ld,"
                "\"ok\":%ld,\"timeout\":%ld,\"watchdog\":%ld,\"parity\":%ld,\"mean_cycles\":%.3f,\"max_cycles\":%llu}",
                graph.c_str(), lanes, nrand, nstim, seed, st.mismatches, st.ok, st.timeout, st.watchdog, st.parity,
                st.n ? (double)st.cycles_sum / st.n : 0.0, st.cycles_max);
  std::printf("%s\n", buf);
  if (!json.empty()) std::ofstream(json) << buf << "\n";
  top->final();
  delete top;
  return st.mismatches ? 1 : 0;
}
