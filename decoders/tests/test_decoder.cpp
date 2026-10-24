// Unit tests: FastDecoder == ReferenceDecoder (bit-exact corrections), corrections are valid
// (their syndrome equals the defect set), determinism, directed corner cases.
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>

#include "qsx/decoder.hpp"

using namespace qsx;

static int failures = 0;
#define CHECK(c)                                                         \
  do {                                                                   \
    if (!(c)) {                                                          \
      std::fprintf(stderr, "CHECK failed %s:%d: %s\n", __FILE__, __LINE__, #c); \
      if (++failures > 20) std::exit(1);                                 \
    }                                                                    \
  } while (0)

static bool valid_correction(const Graph& g, const std::vector<uint8_t>& defect, const DecodeResult& r) {
  std::vector<uint8_t> s(g.V, 0);
  for (int e : r.corr) {
    s[g.eu[e]] ^= 1;
    if (g.ev[e] < g.V) s[g.ev[e]] ^= 1;
  }
  return s == defect;
}

static void run_graph(const std::string& path, int shots, uint64_t seed) {
  Graph g = Graph::load(path);
  ReferenceDecoder ref(g);
  FastDecoder fast(g);
  std::mt19937_64 rng(seed);
  const double dens[] = {0.0, 0.002, 0.01, 0.03, 0.1, 0.3, 0.5, 0.9};
  std::vector<uint8_t> defect(g.V);
  int ok = 0;
  HwModel hw1(g, HwParams{1, 255, 0}), hw8(g, HwParams{8, 255, 0});
  uint64_t cyc_sum = 0;
  for (int i = 0; i < shots; i++) {
    double p = dens[i % 8];
    std::bernoulli_distribution b(p);
    for (int v = 0; v < g.V; v++) defect[v] = b(rng);
    DecodeResult a = ref.decode(defect.data());
    const DecodeResult& f = fast.decode_dense(defect.data());
    CHECK(a.status == f.status);
    CHECK(a.rounds == f.rounds);
    CHECK(a.obs == f.obs);
    CHECK(a.corr == f.corr);
    if (a.status == OK) {
      CHECK(valid_correction(g, defect, a));
      ok++;
    }
    HwResult h = hw8.decode(defect.data());
    CHECK(h.status == a.status);
    CHECK(h.rounds == a.rounds);
    if (a.status == OK) CHECK(h.corr == a.corr && h.obs == a.obs);
    HwResult h1 = hw1.decode(defect.data());
    CHECK(h1.corr == h.corr);
    CHECK(h1.cycles - h.cycles == static_cast<uint64_t>(2 * (h.rounds + 1) * (hw1.nch() - hw8.nch())));
    cyc_sum += h.cycles;
    // watchdog: a budget one below the need must abort, an exact budget must not
    if (i % 97 == 0 && h.cycles > 1) {
      HwModel tight(g, HwParams{8, 255, static_cast<uint32_t>(h.cycles - 1)});
      CHECK(tight.decode(defect.data()).status == WATCHDOG);
      HwModel exact(g, HwParams{8, 255, static_cast<uint32_t>(h.cycles)});
      CHECK(exact.decode(defect.data()).status == h.status);
    }
  }
  // directed: empty, single defect at every vertex, all defects
  for (int v = 0; v < g.V; v++) {
    std::fill(defect.begin(), defect.end(), 0);
    defect[v] = 1;
    DecodeResult a = ref.decode(defect.data());
    CHECK(a.status == OK && valid_correction(g, defect, a));
    CHECK(a.corr == fast.decode_dense(defect.data()).corr);
  }
  std::fill(defect.begin(), defect.end(), 1);
  DecodeResult a = ref.decode(defect.data());
  CHECK(a.corr == fast.decode_dense(defect.data()).corr);
  // timeout path: max_rounds=0 with a defect must report TIMEOUT
  ReferenceDecoder ref0(g, 0);
  FastDecoder fast0(g, 0);
  std::fill(defect.begin(), defect.end(), 0);
  defect[0] = 1;
  CHECK(ref0.decode(defect.data()).status == TIMEOUT);
  CHECK(fast0.decode_dense(defect.data()).status == TIMEOUT);
  std::printf("%s: V=%d E=%d shots=%d ok=%d mean_hw_cycles(P=8)=%.1f failures=%d\n", path.c_str(), g.V, g.E, shots, ok,
              static_cast<double>(cyc_sum) / shots, failures);
}

int main(int argc, char** argv) {
  const char* se = std::getenv("QSX_SHOTS");
  int shots = se ? std::atoi(se) : 2000;
  for (int i = 1; i < argc; i += 1) {
    std::string a = argv[i];
    if (a.size() > 5 && a.substr(a.size() - 5) == ".qsxg") run_graph(a, shots, 1234 + i);
  }
  return failures ? 1 : 0;
}
