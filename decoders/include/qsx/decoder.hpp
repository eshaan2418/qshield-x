// QShield-X union-find decoder ("QSX-UF"). Semantics: DECISIONS.md D1.
//
// Two implementations of the same deterministic semantics:
//   * ReferenceDecoder — dense, recomputes everything each round; the readable specification.
//   * FastDecoder      — sparse, incremental union-find; used for benchmarks.
// Both must produce identical correction sets (tested in decoders/tests).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace qsx {

enum Status : uint8_t { OK = 0, TIMEOUT = 1, PARITY_ERROR = 2 };

struct Graph {
  int V = 0;  // detectors; vertex index V is the virtual boundary
  int E = 0;
  int O = 0;
  std::vector<int> eu, ev;        // ev[e] == V for boundary edges
  std::vector<uint8_t> thr;       // growth threshold in [1,15]
  std::vector<uint64_t> obs;      // observable mask
  std::vector<double> prob;
  // CSR incidence, per vertex sorted by edge index (includes boundary edge).
  std::vector<int> adj_off, adj_e, adj_w;
  std::vector<int> bedge;         // boundary edge of v or -1
  int max_deg = 0;

  static Graph load(const std::string& path);
  void finalize();                // builds CSR / bedge from eu/ev
  int other(int e, int v) const { return eu[e] == v ? ev[e] : eu[e]; }
};

struct DecodeResult {
  Status status = OK;
  uint64_t obs = 0;               // predicted observable flips
  int rounds = 0;                 // growth rounds executed
  std::vector<int> corr;          // corrected edge indices, ascending
};

class ReferenceDecoder {
 public:
  explicit ReferenceDecoder(const Graph& g, int max_rounds = 255) : g_(g), max_rounds_(max_rounds) {}
  // defect: dense 0/1 array of length V.
  DecodeResult decode(const uint8_t* defect) const;

 private:
  const Graph& g_;
  int max_rounds_;
};

class FastDecoder {
 public:
  explicit FastDecoder(const Graph& g, int max_rounds = 255);
  // defects: sparse list of defect vertex indices (any order, no duplicates).
  const DecodeResult& decode(const int* defects, int n);
  const DecodeResult& decode_dense(const uint8_t* defect);

 private:
  int find(int x);
  void unite(int a, int b);

  const Graph& g_;
  int max_rounds_;
  // per-vertex state (reset lazily via touched list)
  std::vector<int> parent_, next_, tail_, dist_, pe_;
  std::vector<uint8_t> rank_, parity_, bnd_, defect_, acc_, in_list_;
  std::vector<int> touched_v_;
  // per-edge state
  std::vector<uint8_t> support_;
  std::vector<int> touched_e_;
  // scratch
  std::vector<int> act_, act2_, grown_, order_, dense_scratch_;
  DecodeResult res_;
};

// Pack/unpack a correction list into an E-bit little-endian bitmap of 32-bit words.
std::vector<uint32_t> corr_bitmap(const Graph& g, const std::vector<int>& corr);

}  // namespace qsx
