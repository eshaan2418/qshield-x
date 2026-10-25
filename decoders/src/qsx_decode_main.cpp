// qsx_decode: decode Stim b8 detection-event files with QSX-UF and report errors + latency.
//
//   qsx_decode --graph g.qsxg --dets dets.b8 --obs obs.b8 --shots N [--out pred.b8]
//              [--impl fast|ref] [--max-rounds R] [--json out.json]
//
// Per-shot latency is wall-clock around decode() only (std::chrono::steady_clock).
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "qsx/decoder.hpp"

using namespace qsx;

static std::vector<uint8_t> read_all(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  if (!f) {
    std::fprintf(stderr, "cannot open %s\n", p.c_str());
    std::exit(2);
  }
  return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}

int main(int argc, char** argv) {
  std::string graph, dets, obs, out, json, impl = "fast";
  long shots = -1;
  int max_rounds = 255, reps = 1;
  double budget_ns = 0;  // optional deadline: report how many blocks took longer
  for (int i = 1; i + 1 < argc; i += 2) {
    std::string k = argv[i], v = argv[i + 1];
    if (k == "--graph") graph = v;
    else if (k == "--dets") dets = v;
    else if (k == "--obs") obs = v;
    else if (k == "--out") out = v;
    else if (k == "--json") json = v;
    else if (k == "--impl") impl = v;
    else if (k == "--shots") shots = std::atol(v.c_str());
    else if (k == "--max-rounds") max_rounds = std::atoi(v.c_str());
    else if (k == "--reps") reps = std::atoi(v.c_str());
    else if (k == "--budget-ns") budget_ns = std::atof(v.c_str());
    else {
      std::fprintf(stderr, "unknown arg %s\n", k.c_str());
      return 2;
    }
  }
  Graph g = Graph::load(graph);
  const int db = (g.V + 7) / 8, ob = (g.O + 7) / 8;
  std::vector<uint8_t> D = read_all(dets), O;
  if (!obs.empty()) O = read_all(obs);
  if (shots < 0) shots = static_cast<long>(D.size() / db);
  if (static_cast<long>(D.size()) < shots * db) {
    std::fprintf(stderr, "dets file too short\n");
    return 2;
  }
  FastDecoder fast(g, max_rounds);
  ReferenceDecoder ref(g, max_rounds);
  std::vector<uint8_t> pred(shots * ob, 0), dense(g.V);
  std::vector<int> sparse;
  std::vector<double> lat;
  lat.reserve(shots);
  long errors = 0, timeouts = 0, parity_errors = 0, total_rounds = 0;
  using clk = std::chrono::steady_clock;
  auto t_all0 = clk::now();
  for (int rep = 0; rep < reps; rep++) {
    for (long s = 0; s < shots; s++) {
      const uint8_t* row = &D[s * db];
      sparse.clear();
      for (int v = 0; v < g.V; v++)
        if ((row[v >> 3] >> (v & 7)) & 1) sparse.push_back(v);
      DecodeResult tmp;
      const DecodeResult* r;
      auto t0 = clk::now();
      if (impl == "ref") {
        std::fill(dense.begin(), dense.end(), 0);
        for (int v : sparse) dense[v] = 1;
        tmp = ref.decode(dense.data());
        r = &tmp;
      } else {
        r = &fast.decode(sparse.data(), static_cast<int>(sparse.size()));
      }
      auto t1 = clk::now();
      if (rep > 0) continue;
      lat.push_back(std::chrono::duration<double, std::nano>(t1 - t0).count());
      total_rounds += r->rounds;
      if (r->status == TIMEOUT) timeouts++;
      if (r->status == PARITY_ERROR) parity_errors++;
      uint64_t p = r->status == OK ? r->obs : 0;
      for (int k = 0; k < ob; k++) pred[s * ob + k] = static_cast<uint8_t>(p >> (8 * k));
      if (!O.empty()) {
        uint64_t truth = 0;
        for (int k = 0; k < ob; k++) truth |= static_cast<uint64_t>(O[s * ob + k]) << (8 * k);
        if (truth != p || r->status != OK) errors++;
      }
    }
  }
  double wall = std::chrono::duration<double>(clk::now() - t_all0).count();
  std::vector<double> sl = lat;
  std::sort(sl.begin(), sl.end());
  auto q = [&](double f) { return sl.empty() ? 0.0 : sl[std::min<size_t>(sl.size() - 1, static_cast<size_t>(f * sl.size()))]; };
  double mean = 0;
  for (double x : lat) mean += x;
  mean /= std::max<size_t>(1, lat.size());
  if (!out.empty()) {
    std::ofstream f(out, std::ios::binary);
    f.write(reinterpret_cast<const char*>(pred.data()), pred.size());
  }
  long over = 0;
  for (double x : lat) over += budget_ns > 0 && x > budget_ns;
  char buf[1024];
  std::snprintf(buf, sizeof buf,
                "{\"impl\":\"%s\",\"shots\":%ld,\"errors\":%ld,\"timeouts\":%ld,\"parity_errors\":%ld,"
                "\"mean_rounds\":%.4f,\"lat_ns_mean\":%.1f,\"lat_ns_p50\":%.1f,\"lat_ns_p90\":%.1f,"
                "\"lat_ns_p99\":%.1f,\"lat_ns_p999\":%.1f,\"lat_ns_max\":%.1f,\"wall_s\":%.6f,\"reps\":%d,"
                "\"budget_ns\":%.1f,\"over_budget\":%ld}",
                impl.c_str(), shots, errors, timeouts, parity_errors,
                static_cast<double>(total_rounds) / std::max(1L, shots), mean, q(0.5), q(0.9), q(0.99), q(0.999),
                sl.empty() ? 0.0 : sl.back(), wall, reps, budget_ns, over);
  std::printf("%s\n", buf);
  if (!json.empty()) {
    std::ofstream f(json);
    f << buf << "\n";
  }
  return 0;
}
