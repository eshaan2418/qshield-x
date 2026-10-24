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
  std::printf("%s: V=%d E=%d shots=%d ok=%d failures=%d\n", path.c_str(), g.V, g.E, shots, ok, failures);
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
