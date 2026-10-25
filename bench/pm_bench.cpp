// pm_bench: decode Stim b8 detection events with PyMatching v2 (sparse blossom, C++ API),
// timing each shot with the same method as qsx_decode (steady_clock around the decode call).
//   pm_bench --dem c.dem --dets dets.b8 --obs obs.b8 [--json out.json]
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "pymatching/sparse_blossom/driver/mwpm_decoding.h"
#include "stim.h"

static std::vector<uint8_t> read_all(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}

int main(int argc, char** argv) {
  std::string dem_path, dets, obs, json;
  double budget_ns = 0;  // optional deadline: report how many blocks took longer
  for (int i = 1; i + 1 < argc; i += 2) {
    std::string k = argv[i], v = argv[i + 1];
    if (k == "--dem") dem_path = v;
    else if (k == "--dets") dets = v;
    else if (k == "--obs") obs = v;
    else if (k == "--json") json = v;
    else if (k == "--budget-ns") budget_ns = std::atof(v.c_str());
  }
  FILE* f = std::fopen(dem_path.c_str(), "r");
  if (!f) return 2;
  stim::DetectorErrorModel dem = stim::DetectorErrorModel::from_file(f);
  std::fclose(f);
  pm::Mwpm mwpm = pm::detector_error_model_to_mwpm(dem, 1000);  // PyMatching default
  const size_t V = dem.count_detectors(), O = dem.count_observables();
  const size_t db = (V + 7) / 8, ob = (O + 7) / 8;
  auto D = read_all(dets), Ob = read_all(obs);
  const size_t shots = D.size() / db;
  std::vector<uint64_t> ev;
  std::vector<uint8_t> pred(O);
  std::vector<double> lat;
  lat.reserve(shots);
  long errors = 0;
  using clk = std::chrono::steady_clock;
  auto t_all0 = clk::now();
  for (size_t s = 0; s < shots; s++) {
    ev.clear();
    for (size_t v = 0; v < V; v++)
      if ((D[s * db + (v >> 3)] >> (v & 7)) & 1) ev.push_back(v);
    std::fill(pred.begin(), pred.end(), 0);
    pm::total_weight_int w = 0;
    auto t0 = clk::now();
    pm::decode_detection_events(mwpm, ev, pred.data(), w, false);
    auto t1 = clk::now();
    lat.push_back(std::chrono::duration<double, std::nano>(t1 - t0).count());
    bool err = false;
    for (size_t k = 0; k < O; k++) err |= pred[k] != ((Ob[s * ob + (k >> 3)] >> (k & 7)) & 1);
    errors += err;
  }
  double wall = std::chrono::duration<double>(clk::now() - t_all0).count();
  std::vector<double> sl = lat;
  std::sort(sl.begin(), sl.end());
  auto q = [&](double fr) { return sl.empty() ? 0.0 : sl[std::min(sl.size() - 1, (size_t)(fr * sl.size()))]; };
  double mean = 0;
  for (double x : lat) mean += x;
  mean /= std::max<size_t>(1, lat.size());
  long over = 0;
  for (double x : lat) over += budget_ns > 0 && x > budget_ns;
  char buf[768];
  std::snprintf(buf, sizeof buf,
                "{\"impl\":\"pymatching-2.4.0-cpp\",\"shots\":%zu,\"errors\":%ld,\"lat_ns_mean\":%.1f,"
                "\"lat_ns_p50\":%.1f,\"lat_ns_p90\":%.1f,\"lat_ns_p99\":%.1f,\"lat_ns_p999\":%.1f,"
                "\"lat_ns_max\":%.1f,\"wall_s\":%.6f,\"budget_ns\":%.1f,\"over_budget\":%ld}",
                shots, errors, mean, q(0.5), q(0.9), q(0.99), q(0.999), sl.empty() ? 0.0 : sl.back(), wall, budget_ns,
                over);
  std::printf("%s\n", buf);
  if (!json.empty()) std::ofstream(json) << buf << "\n";
  return 0;
}
