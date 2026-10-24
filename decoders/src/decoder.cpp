#include "qsx/decoder.hpp"

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace qsx {

Graph Graph::load(const std::string& path) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open graph " + path);
  std::string tag, line;
  int ver = 0;
  f >> tag >> ver;
  if (tag != "qsxg" || ver != 1) throw std::runtime_error("bad graph header");
  Graph g;
  std::string s;
  f >> s >> g.V >> s >> g.E >> s >> g.O;
  std::getline(f, line);
  std::getline(f, line);  // meta
  g.eu.resize(g.E);
  g.ev.resize(g.E);
  g.thr.resize(g.E);
  g.obs.resize(g.E);
  g.prob.resize(g.E);
  for (int e = 0; e < g.E; e++) {
    int t;
    f >> g.eu[e] >> g.ev[e] >> t >> g.obs[e] >> g.prob[e];
    if (t < 1 || t > 15) throw std::runtime_error("threshold out of range");
    g.thr[e] = static_cast<uint8_t>(t);
  }
  if (!f) throw std::runtime_error("truncated graph");
  g.finalize();
  return g;
}

void Graph::finalize() {
  E = static_cast<int>(eu.size());
  std::vector<int> deg(V, 0);
  bedge.assign(V, -1);
  for (int e = 0; e < E; e++) {
    if (eu[e] < 0 || eu[e] >= V || ev[e] <= eu[e] || ev[e] > V)
      throw std::runtime_error("edge endpoints not canonical");
    if (e > 0 && !(eu[e - 1] < eu[e] || (eu[e - 1] == eu[e] && ev[e - 1] < ev[e])))
      throw std::runtime_error("edges not sorted/unique");
    deg[eu[e]]++;
    if (ev[e] < V) deg[ev[e]]++;
    else {
      if (bedge[eu[e]] != -1) throw std::runtime_error("duplicate boundary edge");
      bedge[eu[e]] = e;
    }
  }
  adj_off.assign(V + 1, 0);
  for (int v = 0; v < V; v++) adj_off[v + 1] = adj_off[v] + deg[v];
  max_deg = 0;
  for (int v = 0; v < V; v++) max_deg = std::max(max_deg, deg[v]);
  adj_e.assign(adj_off[V], 0);
  adj_w.assign(adj_off[V], 0);
  std::vector<int> fill(adj_off.begin(), adj_off.end() - 1);
  for (int e = 0; e < E; e++) {  // ascending e => per-vertex lists sorted by edge index
    adj_e[fill[eu[e]]] = e;
    adj_w[fill[eu[e]]++] = ev[e];
    if (ev[e] < V) {
      adj_e[fill[ev[e]]] = e;
      adj_w[fill[ev[e]]++] = eu[e];
    }
  }
}

std::vector<uint32_t> corr_bitmap(const Graph& g, const std::vector<int>& corr) {
  std::vector<uint32_t> w((g.E + 31) / 32, 0);
  for (int e : corr) w[e >> 5] |= 1u << (e & 31);
  return w;
}

// ---------------------------------------------------------------------------------------------
// Reference decoder: literal transcription of DECISIONS.md D1.
// ---------------------------------------------------------------------------------------------
DecodeResult ReferenceDecoder::decode(const uint8_t* defect) const {
  const Graph& g = g_;
  const int V = g.V, E = g.E;
  std::vector<uint8_t> support(E, 0);
  std::vector<int> comp(V), stack;
  std::vector<uint8_t> cpar, cbnd, active(V);
  auto grown = [&](int e) { return support[e] == g.thr[e]; };

  auto clusters = [&]() {
    // components over grown non-boundary edges; comp id = min vertex (first found ascending)
    std::fill(comp.begin(), comp.end(), -1);
    cpar.assign(V, 0);
    cbnd.assign(V, 0);
    for (int s = 0; s < V; s++) {
      if (comp[s] != -1) continue;
      comp[s] = s;
      stack.assign(1, s);
      while (!stack.empty()) {
        int x = stack.back();
        stack.pop_back();
        cpar[s] ^= defect[x];
        if (g.bedge[x] >= 0 && grown(g.bedge[x])) cbnd[s] = 1;
        for (int k = g.adj_off[x]; k < g.adj_off[x + 1]; k++) {
          int e = g.adj_e[k], w = g.adj_w[k];
          if (w < V && grown(e) && comp[w] == -1) {
            comp[w] = s;
            stack.push_back(w);
          }
        }
      }
    }
    bool any = false;
    for (int v = 0; v < V; v++) {
      active[v] = cpar[comp[v]] && !cbnd[comp[v]];
      any |= active[v];
    }
    return any;
  };

  DecodeResult r;
  while (clusters()) {
    if (r.rounds == max_rounds_) {
      r.status = TIMEOUT;
      return r;
    }
    std::vector<uint8_t> next = support;
    for (int e = 0; e < E; e++) {
      int inc = active[g.eu[e]] + (g.ev[e] < V ? active[g.ev[e]] : 0);
      next[e] = static_cast<uint8_t>(std::min<int>(g.thr[e], support[e] + inc));
    }
    support.swap(next);
    r.rounds++;
  }

  // Canonical forest: multi-source BFS.
  const int INF = 1 << 30;
  std::vector<int> dist(V, INF), q;
  for (int v = 0; v < V; v++) {
    int c = comp[v];
    if (cbnd[c]) {
      if (g.bedge[v] >= 0 && grown(g.bedge[v])) dist[v] = 1;
    } else if (c == v) {
      dist[v] = 0;
    }
  }
  // BFS by levels (dist is the true shortest distance because sources are at levels 0 and 1
  // in disjoint components).
  for (int v = 0; v < V; v++)
    if (dist[v] != INF) q.push_back(v);
  for (size_t h = 0; h < q.size(); h++) {
    int x = q[h];
    for (int k = g.adj_off[x]; k < g.adj_off[x + 1]; k++) {
      int e = g.adj_e[k], w = g.adj_w[k];
      if (w < V && grown(e) && dist[w] == INF) {
        dist[w] = dist[x] + 1;
        q.push_back(w);
      }
    }
  }
  std::vector<int> pe(V, -1);
  int maxd = 0;
  for (int v = 0; v < V; v++) {
    maxd = std::max(maxd, dist[v]);
    if (dist[v] == 0) continue;
    if (g.bedge[v] >= 0 && grown(g.bedge[v])) {
      pe[v] = g.bedge[v];
      continue;
    }
    for (int k = g.adj_off[v]; k < g.adj_off[v + 1]; k++) {
      int e = g.adj_e[k], w = g.adj_w[k];
      if (w < V && grown(e) && dist[w] == dist[v] - 1) {
        pe[v] = e;
        break;
      }
    }
  }
  std::vector<uint8_t> acc(defect, defect + V), corr(E, 0);
  for (int dd = maxd; dd >= 0; dd--) {
    for (int v = 0; v < V; v++) {
      if (dist[v] != dd) continue;
      if (dd == 0) {
        if (acc[v]) r.status = PARITY_ERROR;
        continue;
      }
      int e = pe[v];
      if (acc[v]) {
        corr[e] = 1;
        int w = g.other(e, v);
        if (w < V) acc[w] ^= 1;
      }
    }
  }
  for (int e = 0; e < E; e++)
    if (corr[e]) {
      r.corr.push_back(e);
      r.obs ^= g.obs[e];
    }
  return r;
}

// ---------------------------------------------------------------------------------------------
// Fast decoder.
// ---------------------------------------------------------------------------------------------
FastDecoder::FastDecoder(const Graph& g, int max_rounds) : g_(g), max_rounds_(max_rounds) {
  const int V = g.V;
  parent_.resize(V);
  next_.assign(V, -1);
  tail_.resize(V);
  dist_.assign(V, -1);
  pe_.assign(V, -1);
  rank_.assign(V, 0);
  parity_.assign(V, 0);
  bnd_.assign(V, 0);
  defect_.assign(V, 0);
  acc_.assign(V, 0);
  in_list_.assign(V, 0);
  for (int v = 0; v < V; v++) parent_[v] = tail_[v] = v;
  support_.assign(g.E, 0);
}

int FastDecoder::find(int x) {
  while (parent_[x] != x) {
    parent_[x] = parent_[parent_[x]];  // path halving
    x = parent_[x];
  }
  return x;
}

void FastDecoder::unite(int a, int b) {
  a = find(a);
  b = find(b);
  if (a == b) return;
  if (rank_[a] < rank_[b]) std::swap(a, b);
  parent_[b] = a;
  if (rank_[a] == rank_[b]) rank_[a]++;
  parity_[a] ^= parity_[b];
  bnd_[a] |= bnd_[b];
  next_[tail_[a]] = b;  // concatenate member lists
  tail_[a] = tail_[b];
}

const DecodeResult& FastDecoder::decode_dense(const uint8_t* defect) {
  dense_scratch_.clear();
  for (int v = 0; v < g_.V; v++)
    if (defect[v]) dense_scratch_.push_back(v);
  return decode(dense_scratch_.data(), static_cast<int>(dense_scratch_.size()));
}

const DecodeResult& FastDecoder::decode(const int* defects, int n) {
  const Graph& g = g_;
  const int V = g.V;
  // reset state touched by the previous call
  for (int v : touched_v_) {
    parent_[v] = tail_[v] = v;
    next_[v] = -1;
    rank_[v] = parity_[v] = bnd_[v] = defect_[v] = acc_[v] = in_list_[v] = 0;
    dist_[v] = -1;
    pe_[v] = -1;
  }
  touched_v_.clear();
  for (int e : touched_e_) support_[e] = 0;
  touched_e_.clear();
  res_.status = OK;
  res_.obs = 0;
  res_.rounds = 0;
  res_.corr.clear();

  act_.clear();
  for (int i = 0; i < n; i++) {
    int v = defects[i];
    defect_[v] = 1;
    parity_[v] = 1;
    touched_v_.push_back(v);
    act_.push_back(v);
  }
  // Growth rounds.
  for (;;) {
    // filter to distinct active roots
    act2_.clear();
    for (int r : act_) {
      r = find(r);
      if (parity_[r] && !bnd_[r] && !in_list_[r]) {
        in_list_[r] = 1;
        act2_.push_back(r);
      }
    }
    for (int r : act2_) in_list_[r] = 0;
    act_.swap(act2_);
    if (act_.empty()) break;
    if (res_.rounds == max_rounds_) {
      res_.status = TIMEOUT;
      return res_;
    }
    grown_.clear();
    for (int r : act_) {
      for (int v = r; v != -1; v = next_[v]) {
        for (int k = g.adj_off[v]; k < g.adj_off[v + 1]; k++) {
          int e = g.adj_e[k];
          uint8_t s = support_[e];
          if (s >= g.thr[e]) continue;
          if (s == 0) touched_e_.push_back(e);
          support_[e] = ++s;
          if (s == g.thr[e]) grown_.push_back(e);
        }
      }
    }
    for (int e : grown_) {
      int u = g.eu[e], w = g.ev[e];
      if (w == V) {
        bnd_[find(u)] = 1;
      } else {
        touched_v_.push_back(w);  // record for lazy reset (duplicates are harmless)
        touched_v_.push_back(u);
        unite(u, w);
      }
    }
    res_.rounds++;
  }

  // Canonical forest over each non-trivial cluster. Collect distinct roots of defect clusters.
  act2_.clear();
  for (int i = 0; i < n; i++) {
    int r = find(defects[i]);
    if (!in_list_[r]) {
      in_list_[r] = 1;
      act2_.push_back(r);
    }
  }
  for (int r : act2_) in_list_[r] = 0;

  for (int r : act2_) {
    order_.clear();
    if (bnd_[r]) {
      for (int v = r; v != -1; v = next_[v]) {
        int b = g.bedge[v];
        if (b >= 0 && support_[b] == g.thr[b]) {
          dist_[v] = 1;
          pe_[v] = b;
          order_.push_back(v);
        }
      }
      std::sort(order_.begin(), order_.end());  // deterministic BFS seeding (not semantic)
    } else {
      int m = r;
      for (int v = r; v != -1; v = next_[v]) m = std::min(m, v);
      dist_[m] = 0;
      order_.push_back(m);
    }
    for (size_t h = 0; h < order_.size(); h++) {
      int x = order_[h];
      for (int k = g.adj_off[x]; k < g.adj_off[x + 1]; k++) {
        int e = g.adj_e[k], w = g.adj_w[k];
        if (w < V && support_[e] == g.thr[e] && dist_[w] < 0) {
          dist_[w] = dist_[x] + 1;
          order_.push_back(w);
        }
      }
    }
    // parent edges for non-seed vertices: lowest-index grown edge towards dist-1
    for (int x : order_) {
      if (dist_[x] == 0 || pe_[x] >= 0) continue;
      for (int k = g.adj_off[x]; k < g.adj_off[x + 1]; k++) {
        int e = g.adj_e[k], w = g.adj_w[k];
        if (w < V && support_[e] == g.thr[e] && dist_[w] == dist_[x] - 1) {
          pe_[x] = e;
          break;
        }
      }
    }
    // peel in reverse BFS order (non-increasing dist)
    for (int x : order_) acc_[x] = defect_[x];
    for (size_t h = order_.size(); h-- > 0;) {
      int x = order_[h];
      if (dist_[x] == 0) {
        if (acc_[x]) res_.status = PARITY_ERROR;
        continue;
      }
      if (acc_[x]) {
        int e = pe_[x];
        res_.corr.push_back(e);
        res_.obs ^= g.obs[e];
        int w = g.other(e, x);
        if (w < V) acc_[w] ^= 1;
      }
    }
  }
  std::sort(res_.corr.begin(), res_.corr.end());
  return res_;
}

}  // namespace qsx

// ---------------------------------------------------------------------------------------------
// Cycle-exact transaction model of the RTL core.
// ---------------------------------------------------------------------------------------------
namespace qsx {

HwModel::HwModel(const Graph& g, HwParams p) : g_(g), p_(p) {
  nch_ = (g.V + p.lanes - 1) / p.lanes;
}

HwResult HwModel::decode(const uint8_t* defect) {
  const Graph& g = g_;
  const int V = g.V, E = g.E;
  const int INF = 1 << 30;
  HwResult r;
  support_.assign(E, 0);
  label_.resize(V);
  for (int v = 0; v < V; v++) label_[v] = v;
  active_.assign(V, 0);
  vbnd_.assign(V, 0);
  auto grown = [&](int e) { return support_[e] == g.thr[e]; };
  auto bgrown = [&](int v) { return g.bedge[v] >= 0 && grown(g.bedge[v]); };
  uint64_t cyc = 0;
  std::vector<uint64_t> grow_at;  // work-cycle index (1-based) of each GROW, for watchdog accounting
  for (;;) {
    // S_LABEL: synchronous min-label propagation until a no-change cycle
    for (;;) {
      label_n_ = label_;
      for (int v = 0; v < V; v++)
        for (int k = g.adj_off[v]; k < g.adj_off[v + 1]; k++) {
          int e = g.adj_e[k], w = g.adj_w[k];
          if (w < V && grown(e)) label_n_[v] = std::min(label_n_[v], label_[w]);
        }
      cyc++;
      r.label_iters++;
      bool ch = label_n_ != label_;
      label_.swap(label_n_);
      if (!ch) break;
    }
    // S_PAR, S_ACT: NCH cycles each
    par_.assign(V, 0);
    bnd_.assign(V, 0);
    for (int v = 0; v < V; v++) {
      par_[label_[v]] ^= defect[v];
      if (bgrown(v)) bnd_[label_[v]] = 1;
    }
    bool any = false;
    for (int v = 0; v < V; v++) {
      active_[v] = par_[label_[v]] && !bnd_[label_[v]];
      vbnd_[v] = bnd_[label_[v]];
      any |= active_[v];
    }
    cyc += 2 * nch_;
    cyc += 1;  // S_CHK
    if (!any) break;
    if (r.rounds == p_.max_rounds) {
      r.status = TIMEOUT;
      break;
    }
    for (int e = 0; e < E; e++) {  // S_GROW
      int inc = active_[g.eu[e]] + (g.ev[e] < V ? active_[g.ev[e]] : 0);
      support_[e] = static_cast<uint8_t>(std::min<int>(g.thr[e], support_[e] + inc));
    }
    cyc += 1;
    grow_at.push_back(cyc);
    r.rounds++;
  }
  if (r.status == OK) {
    // S_DINIT
    dist_.assign(V, INF);
    for (int v = 0; v < V; v++) {
      if (vbnd_[v]) {
        if (bgrown(v)) dist_[v] = 1;
      } else if (label_[v] == v) {
        dist_[v] = 0;
      }
    }
    cyc += 1;
    // S_DIST
    for (;;) {
      dist_n_ = dist_;
      for (int v = 0; v < V; v++)
        for (int k = g.adj_off[v]; k < g.adj_off[v + 1]; k++) {
          int e = g.adj_e[k], w = g.adj_w[k];
          if (w < V && grown(e) && dist_[w] != INF) dist_n_[v] = std::min(dist_n_[v], dist_[w] + 1);
        }
      cyc++;
      r.dist_iters++;
      bool ch = dist_n_ != dist_;
      dist_.swap(dist_n_);
      if (!ch) break;
    }
    // S_PEH
    pe_.assign(V, -1);
    for (int v = 0; v < V; v++) {
      if (dist_[v] == 0 || dist_[v] == INF) continue;
      if (bgrown(v)) {
        pe_[v] = g.bedge[v];
        continue;
      }
      for (int k = g.adj_off[v]; k < g.adj_off[v + 1]; k++) {
        int e = g.adj_e[k], w = g.adj_w[k];
        if (w < V && grown(e) && dist_[w] == dist_[v] - 1) {
          pe_[v] = e;
          break;
        }
      }
    }
    cyc += 1;
    // S_PEEL: self-timed; a vertex fires once all its children are done.
    done_.assign(V, 0);
    corr_.assign(E, 0);
    int ndone = 0;
    std::vector<int> fire;
    while (ndone < V) {
      fire.clear();
      for (int v = 0; v < V; v++) {
        if (done_[v]) continue;
        bool ready = true;
        for (int k = g.adj_off[v]; k < g.adj_off[v + 1] && ready; k++) {
          int e = g.adj_e[k], w = g.adj_w[k];
          if (w < V && pe_[w] == e && !done_[w]) ready = false;
        }
        if (ready) fire.push_back(v);
      }
      cyc++;
      r.peel_iters++;
      if (fire.empty()) {  // unreachable for well-formed state; watchdog will catch it in RTL
        r.status = WATCHDOG;
        break;
      }
      for (int v : fire) {
        uint8_t acc = defect[v];
        for (int k = g.adj_off[v]; k < g.adj_off[v + 1]; k++) {
          int e = g.adj_e[k], w = g.adj_w[k];
          if (w < V && pe_[w] == e) acc ^= corr_[e];
        }
        if (pe_[v] >= 0) corr_[pe_[v]] = acc;
        else if (acc) r.status = PARITY_ERROR;
      }
      for (int v : fire) done_[v] = 1;
      ndone += static_cast<int>(fire.size());
    }
    if (r.status == OK)
      for (int e = 0; e < E; e++)
        if (corr_[e]) {
          r.corr.push_back(e);
          r.obs ^= g.obs[e];
        }
  }
  r.cycles = cyc;
  if (p_.cycle_budget && cyc > p_.cycle_budget) {
    r.status = WATCHDOG;
    r.cycles = p_.cycle_budget;
    r.rounds = 0;  // rounds completed before the abort
    for (uint64_t c : grow_at) r.rounds += c <= p_.cycle_budget;
  }
  if (r.status != OK) {
    r.corr.clear();
    r.obs = 0;
  }
  return r;
}

}  // namespace qsx
