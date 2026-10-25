// Python bindings: qsxdec.Decoder(graph_path).decode_batch(dets_bool[shots, V]) -> (obs, status, rounds)
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <chrono>

#include "qsx/decoder.hpp"

namespace py = pybind11;
using namespace qsx;

struct PyDecoder {
  Graph g;
  FastDecoder fast;
  PyDecoder(const std::string& path, int max_rounds) : g(Graph::load(path)), fast(g, max_rounds) {}

  py::tuple decode_batch(py::array_t<uint8_t, py::array::c_style | py::array::forcecast> dets, bool timing) {
    auto d = dets.unchecked<2>();
    if (d.shape(1) != g.V) throw std::runtime_error("dets must have shape (shots, V)");
    const py::ssize_t n = d.shape(0);
    py::array_t<uint64_t> obs(n);
    py::array_t<uint8_t> status(n);
    py::array_t<int32_t> rounds(n);
    py::array_t<double> lat(timing ? n : 0);
    auto o = obs.mutable_unchecked<1>();
    auto s = status.mutable_unchecked<1>();
    auto r = rounds.mutable_unchecked<1>();
    std::vector<int> sp;
    for (py::ssize_t i = 0; i < n; i++) {
      sp.clear();
      for (int v = 0; v < g.V; v++)
        if (d(i, v)) sp.push_back(v);
      auto t0 = std::chrono::steady_clock::now();
      const DecodeResult& res = fast.decode(sp.data(), static_cast<int>(sp.size()));
      auto t1 = std::chrono::steady_clock::now();
      if (timing) lat.mutable_at(i) = std::chrono::duration<double, std::nano>(t1 - t0).count();
      o(i) = res.status == OK ? res.obs : 0;
      s(i) = res.status;
      r(i) = res.rounds;
    }
    return py::make_tuple(obs, status, rounds, lat);
  }

  // Cycle-exact hardware model (bit-exact with rtl/qsx_uf_core.sv): obs, status, busy cycles.
  py::tuple decode_batch_hw(py::array_t<uint8_t, py::array::c_style | py::array::forcecast> dets, int lanes,
                            int max_rounds, int pipe, bool breakdown) {
    auto d = dets.unchecked<2>();
    if (d.shape(1) != g.V) throw std::runtime_error("dets must have shape (shots, V)");
    const py::ssize_t n = d.shape(0);
    HwModel hw(g, HwParams{lanes, max_rounds, 0, pipe});
    py::array_t<uint64_t> obs(n);
    py::array_t<uint8_t> status(n);
    py::array_t<uint32_t> cycles(n);
    // breakdown: per shot (growth rounds, LABEL iterations, DIST iterations, PEEL iterations)
    py::array_t<uint32_t> parts({static_cast<py::ssize_t>(breakdown ? n : 0), static_cast<py::ssize_t>(4)});
    std::vector<uint8_t> row(g.V);
    for (py::ssize_t i = 0; i < n; i++) {
      for (int v = 0; v < g.V; v++) row[v] = d(i, v);
      HwResult r = hw.decode(row.data());
      obs.mutable_at(i) = r.obs;
      status.mutable_at(i) = r.status;
      cycles.mutable_at(i) = static_cast<uint32_t>(r.cycles);
      if (breakdown) {
        parts.mutable_at(i, 0) = static_cast<uint32_t>(r.rounds);
        parts.mutable_at(i, 1) = static_cast<uint32_t>(r.label_iters);
        parts.mutable_at(i, 2) = static_cast<uint32_t>(r.dist_iters);
        parts.mutable_at(i, 3) = static_cast<uint32_t>(r.peel_iters);
      }
    }
    if (breakdown) return py::make_tuple(obs, status, cycles, parts);
    return py::make_tuple(obs, status, cycles);
  }

  py::list corrections(py::array_t<uint8_t, py::array::c_style | py::array::forcecast> defect) {
    auto d = defect.unchecked<1>();
    std::vector<int> sp;
    for (int v = 0; v < g.V; v++)
      if (d(v)) sp.push_back(v);
    const DecodeResult& res = fast.decode(sp.data(), static_cast<int>(sp.size()));
    py::list l;
    for (int e : res.corr) l.append(e);
    return l;
  }
};

PYBIND11_MODULE(qsxdec, m) {
  py::class_<PyDecoder>(m, "Decoder")
      .def(py::init<const std::string&, int>(), py::arg("graph"), py::arg("max_rounds") = 255)
      .def("decode_batch", &PyDecoder::decode_batch, py::arg("dets"), py::arg("timing") = false)
      .def("corrections", &PyDecoder::corrections)
      .def("decode_batch_hw", &PyDecoder::decode_batch_hw, py::arg("dets"), py::arg("lanes") = 8,
           py::arg("max_rounds") = 255, py::arg("pipe") = 0, py::arg("breakdown") = false)
      .def_property_readonly("V", [](const PyDecoder& p) { return p.g.V; })
      .def_property_readonly("E", [](const PyDecoder& p) { return p.g.E; });
}
