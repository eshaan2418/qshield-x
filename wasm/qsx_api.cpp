// C API shared by the native and WebAssembly builds of the QSX-UF decoder (M4).
// The same translation unit is compiled natively (clang -O3, with and without auto-vectorisation)
// and with Emscripten (-O3, scalar and -msimd128).
#include <cstdint>
#include <cstdlib>
#include <sstream>
#include <string>
#include <vector>

#include "qsx/decoder.hpp"
#include "qsx/unpack.hpp"

#if defined(__EMSCRIPTEN__)
#include <emscripten.h>
#define QSX_EXPORT extern "C" EMSCRIPTEN_KEEPALIVE
static double now_ns() { return emscripten_get_now() * 1e6; }
#else
#include <chrono>
#define QSX_EXPORT extern "C"
static double now_ns() {
  return std::chrono::duration<double, std::nano>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
#endif

using namespace qsx;

static Graph* g_graph = nullptr;
static FastDecoder* g_dec = nullptr;
static HwModel* g_hw = nullptr;  // inspection API; references *g_graph
static int g_hw_lanes = -1, g_hw_pipe = -1;
static std::vector<int> g_sparse;
static uint64_t g_hash = 0;

static inline void fnv(uint64_t& h, uint64_t x) {
  for (int i = 0; i < 8; i++) {
    h ^= (x >> (8 * i)) & 0xff;
    h *= 0x100000001b3ULL;
  }
}

QSX_EXPORT int qsx_init(const char* text) {
  std::istringstream in(text);
  // Same format as Graph::load (decoders/src/decoder.cpp), parsed from memory.
  Graph g;
  std::string tag, s, line;
  int ver;
  in >> tag >> ver >> s >> g.V >> s >> g.E >> s >> g.O;
  if (tag != "qsxg" || ver != 1) return -1;
  std::getline(in, line);
  std::getline(in, line);
  g.eu.resize(g.E);
  g.ev.resize(g.E);
  g.thr.resize(g.E);
  g.obs.resize(g.E);
  g.prob.resize(g.E);
  for (int e = 0; e < g.E; e++) {
    int t;
    in >> g.eu[e] >> g.ev[e] >> t >> g.obs[e] >> g.prob[e];
    g.thr[e] = static_cast<uint8_t>(t);
  }
  if (!in) return -2;
  g.finalize();
  delete g_hw;
  g_hw = nullptr;
  delete g_dec;
  delete g_graph;
  g_graph = new Graph(std::move(g));
  g_dec = new FastDecoder(*g_graph);
  g_sparse.assign(g_graph->V + 64, 0);
  return g_graph->V;
}

QSX_EXPORT int qsx_num_detectors() { return g_graph ? g_graph->V : 0; }
QSX_EXPORT int qsx_num_edges() { return g_graph ? g_graph->E : 0; }
QSX_EXPORT int qsx_has_simd() { return QSX_HAVE_SIMD; }
QSX_EXPORT void* qsx_malloc(int n) { return std::malloc(n); }
QSX_EXPORT void qsx_free(void* p) { std::free(p); }
QSX_EXPORT uint32_t qsx_hash_lo() { return static_cast<uint32_t>(g_hash); }
QSX_EXPORT uint32_t qsx_hash_hi() { return static_cast<uint32_t>(g_hash >> 32); }

static inline int unpack(const uint8_t* row, int variant) {
  const int V = g_graph->V;
  switch (variant) {
    case 0: return unpack_naive(row, V, g_sparse.data());
    case 1: return unpack_word(row, V, g_sparse.data());
    default: return unpack_simd(row, V, g_sparse.data());
  }
}

// Decode `shots` bit-packed rows. pred[s] = predicted observable mask (low 8 bits), 0xff on error
// status. Updates the FNV-1a hash over (status, obs, correction edge list) of every shot.
// If lat_ns != nullptr, per-shot latency (unpack + decode) is written. Returns #non-OK statuses.
QSX_EXPORT int qsx_decode_batch(const uint8_t* bits, int shots, uint8_t* pred, double* lat_ns, int variant) {
  const int rb = (g_graph->V + 7) >> 3;
  int bad = 0;
  g_hash = 0xcbf29ce484222325ULL;
  for (int s = 0; s < shots; s++) {
    const uint8_t* row = bits + static_cast<size_t>(s) * rb;
    double t0 = lat_ns ? now_ns() : 0;
    int n = unpack(row, variant);
    const DecodeResult& r = g_dec->decode(g_sparse.data(), n);
    if (lat_ns) lat_ns[s] = now_ns() - t0;
    bad += r.status != OK;
    pred[s] = r.status == OK ? static_cast<uint8_t>(r.obs) : 0xff;
    fnv(g_hash, (static_cast<uint64_t>(r.status) << 56) ^ r.obs);
    for (int e : r.corr) fnv(g_hash, static_cast<uint64_t>(e));
    fnv(g_hash, ~0ULL);
  }
  return bad;
}

// Throughput loop without per-shot timing (one clock read per call). Returns elapsed ns.
QSX_EXPORT double qsx_bench(const uint8_t* bits, int shots, int reps, int variant) {
  const int rb = (g_graph->V + 7) >> 3;
  uint64_t sink = 0;
  double t0 = now_ns();
  for (int k = 0; k < reps; k++)
    for (int s = 0; s < shots; s++) {
      int n = unpack(bits + static_cast<size_t>(s) * rb, variant);
      sink += g_dec->decode(g_sparse.data(), n).obs;
    }
  double t1 = now_ns();
  g_hash ^= sink;  // keep the loop observable
  return t1 - t0;
}

// Isolated unpack kernel timing (for the M5 codegen study). Returns elapsed ns.
QSX_EXPORT double qsx_bench_unpack(const uint8_t* bits, int shots, int reps, int variant) {
  const int rb = (g_graph->V + 7) >> 3;
  uint64_t sink = 0;
  double t0 = now_ns();
  for (int k = 0; k < reps; k++)
    for (int s = 0; s < shots; s++) sink += unpack(bits + static_cast<size_t>(s) * rb, variant);
  double t1 = now_ns();
  g_hash ^= sink;
  return t1 - t0;
}

// ---------------------------------------------------------------- single-shot inspection API (M9 viz)
// Edge endpoints (v == V denotes the virtual boundary).
QSX_EXPORT int qsx_edge_u(int e) { return g_graph->eu[e]; }
QSX_EXPORT int qsx_edge_v(int e) { return g_graph->ev[e]; }

// Decode one bit-packed row with the golden decoder. Writes up to `cap` corrected edge indices to `edges` and
// info[0] = status, info[1] = observable mask (low 32 bits), info[2] = growth rounds. Returns #corrected edges.
QSX_EXPORT int qsx_decode_one(const uint8_t* row, int* edges, int cap, int* info) {
  int n = unpack(row, 1);
  const DecodeResult& r = g_dec->decode(g_sparse.data(), n);
  info[0] = r.status;
  info[1] = static_cast<int>(r.obs & 0xffffffffu);
  info[2] = r.rounds;
  int k = 0;
  for (int e : r.corr)
    if (k < cap) edges[k++] = e;
  return k;
}

// Busy cycles of the RTL core for this row (cycle-exact qsx::HwModel, verified against the RTL in co-simulation).
QSX_EXPORT int qsx_hw_cycles(const uint8_t* row, int lanes, int pipe) {
  if (!g_hw || lanes != g_hw_lanes || pipe != g_hw_pipe) {
    delete g_hw;
    g_hw = new HwModel(*g_graph, HwParams{lanes, 255, 0, pipe});
    g_hw_lanes = lanes;
    g_hw_pipe = pipe;
  }
  std::vector<uint8_t> dense(g_graph->V, 0);
  for (int v = 0; v < g_graph->V; v++) dense[v] = (row[v >> 3] >> (v & 7)) & 1;
  return static_cast<int>(g_hw->decode(dense.data()).cycles);
}
