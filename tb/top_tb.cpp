// Verilator co-simulation of rtl/qsx_top.sv (AXI-Stream framing, FIFO, config, core) against
// qsx::HwModel. Checks every output frame (magic, tag, status, obs, full correction bitmap).
//
//   top_tb --graph g.qsxg --lanes P [--random N] [--stim dets.b8] [--seed S]
//          [--gap PROB] [--bp PROB] [--malformed PROB] [--reconfig 0|1] [--latency 0|1] [--json f]
//
// --latency 1: frames are sent one at a time with no gaps/backpressure; per-frame end-to-end latency
// (cycles from first input beat accepted to output header accepted) is recorded.
// --reconfig 1: at fixed points (pipeline drained) the TB runs (a) an incomplete session, expecting
// CFG_INVALID responses, then (b) a complete session loading unweighted thresholds (thr=2), then
// (c) a complete session restoring the original thresholds.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <random>
#include <string>
#include <type_traits>
#include <vector>

#include "Vqsx_top.h"
#include "qsx/decoder.hpp"
#include "verilated.h"

using namespace qsx;

template <typename T>
static bool get_bit(const T& s, int b) {
  if constexpr (std::is_integral_v<T>) return (s >> b) & 1;
  else return (s[b >> 5] >> (b & 31)) & 1;
}

struct Expect {
  uint16_t tag;
  int status;
  int obs;
  std::vector<uint32_t> corr;  // CW words
};

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  std::string graph, stim, json;
  int lanes = 8, reconfig = 0, latency_mode = 0, pipe = 0;
  long nrand = 0;
  double gap = 0.0, bp = 0.0, malformed = 0.0;
  unsigned long long seed = 1;
  for (int i = 1; i + 1 < argc; i += 2) {
    std::string k = argv[i], v = argv[i + 1];
    if (k == "--graph") graph = v;
    else if (k == "--lanes") lanes = std::atoi(v.c_str());
    else if (k == "--pipe") pipe = std::atoi(v.c_str());
    else if (k == "--random") nrand = std::atol(v.c_str());
    else if (k == "--stim") stim = v;
    else if (k == "--seed") seed = std::strtoull(v.c_str(), nullptr, 10);
    else if (k == "--gap") gap = std::atof(v.c_str());
    else if (k == "--bp") bp = std::atof(v.c_str());
    else if (k == "--malformed") malformed = std::atof(v.c_str());
    else if (k == "--reconfig") reconfig = std::atoi(v.c_str());
    else if (k == "--latency") latency_mode = std::atoi(v.c_str());
    else if (k == "--json") json = v;
  }
  Graph gq = Graph::load(graph);
  Graph gu = gq;  // unweighted variant for reconfiguration
  std::fill(gu.thr.begin(), gu.thr.end(), 2);
  const int W = (gq.V + 31) / 32, CW = (gq.E + 31) / 32;
  HwModel mq(gq, HwParams{lanes, 255, 0, pipe}), mu(gu, HwParams{lanes, 255, 0, pipe});
  HwModel* model = &mq;
  bool cfg_valid_state = true;

  auto* top = new Vqsx_top;
  std::mt19937_64 rng(seed);
  std::uniform_real_distribution<double> U(0, 1);
  uint64_t cyc = 0;

  // ---- syndrome source
  std::vector<std::vector<uint8_t>> synd;
  const double dens[] = {0.0, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 0.5, 0.9};
  for (long s = 0; s < nrand; s++) {
    std::bernoulli_distribution b(dens[s % 9]);
    std::vector<uint8_t> d(gq.V);
    for (int v = 0; v < gq.V; v++) d[v] = b(rng);
    synd.push_back(std::move(d));
  }
  long nstim = 0;
  if (!stim.empty()) {
    std::ifstream f(stim, std::ios::binary);
    std::vector<uint8_t> D((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    const int db = (gq.V + 7) / 8;
    for (size_t s = 0; s + db <= D.size(); s += db, nstim++) {
      std::vector<uint8_t> d(gq.V);
      for (int v = 0; v < gq.V; v++) d[v] = (D[s + (v >> 3)] >> (v & 7)) & 1;
      synd.push_back(std::move(d));
    }
  }

  // ---- driver state
  std::deque<Expect> exp;
  std::vector<uint32_t> beats;
  size_t beat_i = 0;
  bool have_frame = false;
  size_t next_frame = 0;
  long mism = 0, checked = 0, n_mal = 0, n_cfg_invalid = 0, n_reconf_frames = 0;
  std::vector<uint32_t> out_frame;
  std::vector<double> lat;
  std::deque<uint64_t> t_first;
  bool first_accepted = false;
  long counts[8] = {0};

  auto tick = [&](bool m_ready) {
    top->m_axis_tready = m_ready;
    top->clk = 0;
    top->eval();
    bool s_fire = top->s_axis_tvalid && top->s_axis_tready;
    bool m_fire = top->m_axis_tvalid && top->m_axis_tready;
    uint32_t m_data = top->m_axis_tdata;
    bool m_last = top->m_axis_tlast;
    bool c_fire = top->cfg_valid && top->cfg_ready;
    top->clk = 1;
    top->eval();
    cyc++;
    return std::make_tuple(s_fire, m_fire, m_data, m_last, c_fire);
  };

  auto check_out = [&](const std::vector<uint32_t>& fr) {
    checked++;
    if (exp.empty()) {
      std::fprintf(stderr, "unexpected output frame\n");
      mism++;
      return;
    }
    Expect e = exp.front();
    exp.pop_front();
    uint32_t h = fr[0];
    bool bad = (h >> 24) != 0x5A || (h & 0xffff) != e.tag || ((h >> 20) & 0xf) != (uint32_t)e.status ||
               ((h >> 16) & 1) != (uint32_t)e.obs || fr.size() != (size_t)(1 + CW);
    for (int i = 0; i < CW && !bad; i++) bad |= fr[1 + i] != e.corr[i];
    if (bad) {
      if (mism < 10)
        std::fprintf(stderr, "MISMATCH frame tag=%u: got hdr=%08x len=%zu exp status=%d obs=%d\n", e.tag, h,
                     fr.size(), e.status, e.obs);
      mism++;
    }
    counts[e.status & 7]++;
  };

  auto step = [&](bool allow_send) {
    // prepare input beat
    bool send = allow_send && have_frame && !(gap > 0 && U(rng) < gap);
    top->s_axis_tvalid = send;
    top->s_axis_tdata = send ? beats[beat_i] : 0;
    top->s_axis_tlast = send && beat_i + 1 == beats.size();
    bool mr = !(bp > 0 && U(rng) < bp);
    auto [s_fire, m_fire, m_data, m_last, c_fire] = tick(mr);
    (void)c_fire;
    if (s_fire) {
      if (beat_i == 0 && latency_mode) t_first.push_back(cyc);
      if (++beat_i == beats.size()) have_frame = false;
    }
    if (m_fire) {
      out_frame.push_back(m_data);
      if (m_last) {
        if (latency_mode && (out_frame[0] >> 24) == 0x5A) {}
        check_out(out_frame);
        out_frame.clear();
      }
      if (out_frame.size() == 1 && latency_mode && !t_first.empty()) {
        lat.push_back(static_cast<double>(cyc - t_first.front()));
        t_first.pop_front();
      }
    }
    (void)first_accepted;
  };

  auto make_frame = [&](const std::vector<uint8_t>& d, uint16_t tag) {
    beats.assign(1 + W, 0);
    beats[0] = 0xA5000000u | tag;
    for (int v = 0; v < gq.V; v++)
      if (d[v]) beats[1 + v / 32] |= 1u << (v % 32);
    beat_i = 0;
    have_frame = true;
    Expect e{tag, 0, 0, std::vector<uint32_t>(CW, 0)};
    // malformed injection
    if (malformed > 0 && U(rng) < malformed) {
      n_mal++;
      int kind = static_cast<int>(U(rng) * 3);
      if (kind == 0) beats[0] = 0x11000000u | tag;  // bad magic
      else if (kind == 1 && W >= 1) beats.pop_back();  // short (ends early)
      else beats.push_back(0xdeadbeef);  // long
      e.status = FRAME_ERROR;
      exp.push_back(e);
      return;
    }
    if (!cfg_valid_state) {
      e.status = CFG_INVALID;
      n_cfg_invalid++;
      exp.push_back(e);
      return;
    }
    HwResult r = model->decode(d.data());
    e.status = r.status;
    e.obs = static_cast<int>(r.obs & 1);
    for (int ed : r.corr) e.corr[ed / 32] |= 1u << (ed % 32);
    if (model == &mu) n_reconf_frames++;
    exp.push_back(e);
  };

  auto drain = [&]() {
    long guard = 0;
    while (have_frame || !exp.empty()) {
      step(true);
      if (++guard > 50000000L) {
        std::fprintf(stderr, "drain hang\n");
        std::exit(3);
      }
    }
  };

  auto cfg_write = [&](uint32_t addr, uint32_t data) {
    top->cfg_valid = 1;
    top->cfg_addr = addr;
    top->cfg_wdata = data;
    for (;;) {
      top->s_axis_tvalid = 0;
      auto [s_fire, m_fire, m_data, m_last, c_fire] = tick(true);
      (void)s_fire;
      (void)m_fire;
      (void)m_data;
      (void)m_last;
      if (c_fire) break;
    }
    top->cfg_valid = 0;
  };
  auto cfg_session = [&](const Graph& g, bool complete) {
    cfg_write(0x000, 1);
    cfg_write(0x001, 255);
    cfg_write(0x002, 0);
    const int nw = (g.E + 7) / 8;
    for (int w = 0; w < nw; w++) {
      if (!complete && w == nw / 2) continue;  // skip one word
      uint32_t data = 0;
      for (int i = 0; i < 8 && w * 8 + i < g.E; i++) data |= static_cast<uint32_t>(g.thr[w * 8 + i]) << (4 * i);
      cfg_write(0x100 + w, data);
    }
    cfg_write(0x000, 2);
  };

  // reset
  top->rst_n = 0;
  top->cfg_valid = 0;
  top->s_axis_tvalid = 0;
  for (int i = 0; i < 4; i++) tick(true);
  top->rst_n = 1;
  tick(true);

  const size_t N = synd.size();
  const size_t r1 = N / 4, r2 = N / 4 + std::min<size_t>(50, N / 8), r3 = N / 2;
  for (next_frame = 0; next_frame < N; next_frame++) {
    if (reconfig && (next_frame == r1 || next_frame == r2 || next_frame == r3)) {
      drain();
      if (next_frame == r1) {
        cfg_session(gq, false);
        if (top->cfg_ok) mism++, std::fprintf(stderr, "cfg_ok after incomplete session\n");
        cfg_valid_state = false;
      } else if (next_frame == r2) {
        cfg_session(gu, true);
        if (!top->cfg_ok) mism++, std::fprintf(stderr, "cfg not ok after complete session\n");
        cfg_valid_state = true;
        model = &mu;
      } else {
        cfg_session(gq, true);
        cfg_valid_state = top->cfg_ok;
        model = &mq;
      }
    }
    make_frame(synd[next_frame], static_cast<uint16_t>(next_frame & 0xffff));
    if (latency_mode) drain();
    else {
      long guard = 0;
      while (have_frame) {
        step(true);
        if (++guard > 50000000L) {
          std::fprintf(stderr, "send hang\n");
          return 3;
        }
      }
    }
  }
  drain();
  for (int i = 0; i < 50; i++) step(false);
  if (top->m_axis_tvalid) mism++;

  std::sort(lat.begin(), lat.end());
  auto q = [&](double f) { return lat.empty() ? 0.0 : lat[std::min(lat.size() - 1, (size_t)(f * lat.size()))]; };
  double mean = 0;
  for (double x : lat) mean += x;
  mean /= std::max<size_t>(1, lat.size());
  char buf[1024];
  std::snprintf(buf, sizeof buf,
                "{\"graph\":\"%s\",\"pipe\":%d,\"lanes\":%d,\"frames\":%zu,\"random\":%ld,\"stim\":%ld,\"seed\":%llu,"
                "\"checked\":%ld,\"mismatches\":%ld,\"malformed\":%ld,\"cfg_invalid\":%ld,\"reconf_frames\":%ld,"
                "\"status_counts\":[%ld,%ld,%ld,%ld,%ld,%ld],\"cycles\":%llu,\"gap\":%.3f,\"bp\":%.3f,"
                "\"latency_cycles\":{\"n\":%zu,\"mean\":%.2f,\"p50\":%.0f,\"p99\":%.0f,\"p999\":%.0f,\"max\":%.0f}}",
                graph.c_str(), pipe, lanes, N, nrand, nstim, seed, checked, mism, n_mal, n_cfg_invalid, n_reconf_frames,
                counts[0], counts[1], counts[2], counts[3], counts[4], counts[5], (unsigned long long)cyc, gap, bp,
                lat.size(), mean, q(0.5), q(0.99), q(0.999), lat.empty() ? 0.0 : lat.back());
  std::printf("%s\n", buf);
  if (!json.empty()) std::ofstream(json) << buf << "\n";
  top->final();
  delete top;
  return mism ? 1 : 0;
}
