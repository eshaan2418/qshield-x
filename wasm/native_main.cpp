// Native driver for wasm/qsx_api.cpp: identical decode loops, steady_clock timing.
//   qsx_native --graph g.qsxg --dets d.b8 [--obs o.b8] [--variant 0|1|2] [--reps R]
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

extern "C" {
int qsx_init(const char*);
int qsx_num_detectors();
int qsx_has_simd();
int qsx_decode_batch(const uint8_t*, int, uint8_t*, double*, int);
double qsx_bench(const uint8_t*, int, int, int);
double qsx_bench_unpack(const uint8_t*, int, int, int);
uint32_t qsx_hash_lo();
uint32_t qsx_hash_hi();
}

static std::string slurp(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

int main(int argc, char** argv) {
  std::string graph, dets, obs, label = "native";
  int variant = 2, reps = 5;
  for (int i = 1; i + 1 < argc; i += 2) {
    std::string k = argv[i], v = argv[i + 1];
    if (k == "--graph") graph = v;
    else if (k == "--dets") dets = v;
    else if (k == "--obs") obs = v;
    else if (k == "--variant") variant = std::atoi(v.c_str());
    else if (k == "--reps") reps = std::atoi(v.c_str());
    else if (k == "--label") label = v;
  }
  std::string gt = slurp(graph), D = slurp(dets), O = obs.empty() ? "" : slurp(obs);
  int V = qsx_init(gt.c_str());
  int rb = (V + 7) / 8, shots = static_cast<int>(D.size() / rb);
  const uint8_t* bits = reinterpret_cast<const uint8_t*>(D.data());
  std::vector<uint8_t> pred(shots);
  std::vector<double> lat(shots);
  int bad = qsx_decode_batch(bits, shots, pred.data(), lat.data(), variant);
  uint64_t h = (uint64_t(qsx_hash_hi()) << 32) | qsx_hash_lo();
  long errors = 0;
  if (!O.empty())
    for (int s = 0; s < shots; s++) errors += (pred[s] & 1) != (O[s] & 1);
  std::sort(lat.begin(), lat.end());
  double best = 1e300, ubest = 1e300;
  for (int r = 0; r < reps; r++) {
    best = std::min(best, qsx_bench(bits, shots, 1, variant));
    ubest = std::min(ubest, qsx_bench_unpack(bits, shots, 1, variant));
  }
  std::printf("{\"label\":\"%s\",\"variant\":%d,\"simd\":%d,\"V\":%d,\"shots\":%d,\"bad_status\":%d,\"errors\":%ld,"
              "\"hash\":\"%016llx\",\"lat_ns_p50\":%.1f,\"lat_ns_p99\":%.1f,\"steady_ns_per_shot\":%.2f,"
              "\"unpack_ns_per_shot\":%.2f}\n",
              label.c_str(), variant, qsx_has_simd(), V, shots, bad, errors, (unsigned long long)h,
              lat[shots / 2], lat[static_cast<size_t>(0.99 * shots)], best / shots, ubest / shots);
  return 0;
}
