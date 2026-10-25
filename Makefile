# QShield-X top-level Makefile. All targets source env.sh (project-local toolchains).
SHELL := /bin/bash
ROOT  := $(abspath .)
ENV   := source $(ROOT)/env.sh &&
PY    := $(ROOT)/.venv/bin/python
CXX   ?= clang++
CXXFLAGS ?= -std=c++17 -O3 -Wall -Wextra -Idecoders/include
B     := build
DISTANCES ?= 3 5 7 9

DEC_SRC := decoders/src/decoder.cpp
DEC_HDR := decoders/include/qsx/decoder.hpp decoders/include/qsx/unpack.hpp
PYEXT   := $(shell $(PY) -c "import sysconfig;print(sysconfig.get_config_var('EXT_SUFFIX'))" 2>/dev/null)
PM_SRC  := .tools/src/pymatching
PM_BLD  := .tools/src/pm-build
RTL     := rtl/qsx_min_tree.sv rtl/qsx_uf_core.sv rtl/qsx_ingress.sv rtl/qsx_cfg.sv rtl/qsx_top.sv
WASM_EXP := _qsx_init,_qsx_num_detectors,_qsx_num_edges,_qsx_has_simd,_qsx_malloc,_qsx_free,_qsx_hash_lo,_qsx_hash_hi,_qsx_decode_batch,_qsx_bench,_qsx_bench_unpack,_qsx_edge_u,_qsx_edge_v,_qsx_decode_one,_qsx_hw_cycles
EMFLAGS := -O3 -std=c++17 -Idecoders/include -sMODULARIZE=1 -sEXPORT_NAME=QSXModule -sENVIRONMENT=web,shell,node \
           -sALLOW_MEMORY_GROWTH=1 -sEXPORTED_FUNCTIONS=$(WASM_EXP) -sEXPORTED_RUNTIME_METHODS=HEAPU8,HEAPF64

.PHONY: all graphs decoders pymatching test test-cpp test-py lint cosim cosim-quick formal formal-quick \
        synth wasm native m1 m2hw m4 m5 m6 m7 m8 e2e env viz viz-test figures check-numbers reproduce-quick reproduce-full paper ci clean

all: decoders graphs wasm native

$(B) $(B)/graphs:
	mkdir -p $@

# ---------------------------------------------------------------- graphs
GRAPHS := $(foreach d,$(DISTANCES),$(B)/graphs/d$(d).qsxg)
graphs: $(GRAPHS)
$(B)/graphs/d%.qsxg: sim/qsx_graph.py | $(B)/graphs
	$(PY) sim/qsx_graph.py --d $* --p 0.001 --out $@

# ---------------------------------------------------------------- C++ decoders
decoders: $(B)/qsx_decode $(B)/test_decoder $(B)/qsxdec$(PYEXT)
$(B)/qsx_decode: $(DEC_SRC) $(DEC_HDR) decoders/src/qsx_decode_main.cpp | $(B)
	$(CXX) $(CXXFLAGS) $(DEC_SRC) decoders/src/qsx_decode_main.cpp -o $@
$(B)/test_decoder: $(DEC_SRC) $(DEC_HDR) decoders/tests/test_decoder.cpp | $(B)
	$(CXX) $(CXXFLAGS) -O2 $(DEC_SRC) decoders/tests/test_decoder.cpp -o $@
$(B)/qsxdec$(PYEXT): $(DEC_SRC) $(DEC_HDR) decoders/src/pybind.cpp | $(B)
	$(CXX) $(CXXFLAGS) -shared -fPIC -undefined dynamic_lookup $$($(PY) -m pybind11 --includes) \
	  $(DEC_SRC) decoders/src/pybind.cpp -o $@

# PyMatching v2.4.0 C++ library (reference baseline) + harness
pymatching: $(B)/pm_bench
$(PM_SRC):
	git clone -q --depth 1 --branch v2.4.0 https://github.com/oscarhiggott/PyMatching.git $@
$(PM_BLD)/libpymatching.a: | $(PM_SRC)
	$(ENV) cmake -S $(PM_SRC) -B $(PM_BLD) -G Ninja -DCMAKE_BUILD_TYPE=Release >/dev/null && cmake --build $(PM_BLD) --target libpymatching -j 16
$(B)/pm_bench: bench/pm_bench.cpp $(PM_BLD)/libpymatching.a | $(B)
	$(CXX) -std=c++20 -O3 -I$(PM_SRC)/src -I$(PM_BLD)/_deps/stim-src/src bench/pm_bench.cpp \
	  $(PM_BLD)/libpymatching.a $(PM_BLD)/_deps/stim-build/out/libstim.a -o $@

# ---------------------------------------------------------------- native + wasm builds (M4)
native: $(B)/qsx_native_novec $(B)/qsx_native_simd
$(B)/qsx_native_novec: wasm/qsx_api.cpp wasm/native_main.cpp $(DEC_SRC) $(DEC_HDR) | $(B)
	$(CXX) -std=c++17 -O3 -fno-vectorize -fno-slp-vectorize -DQSX_NO_NEON -Idecoders/include wasm/qsx_api.cpp wasm/native_main.cpp $(DEC_SRC) -o $@
$(B)/qsx_native_simd: wasm/qsx_api.cpp wasm/native_main.cpp $(DEC_SRC) $(DEC_HDR) | $(B)
	$(CXX) -std=c++17 -O3 -Idecoders/include wasm/qsx_api.cpp wasm/native_main.cpp $(DEC_SRC) -o $@
wasm: wasm/dist/qsx_scalar.js wasm/dist/qsx_simd.js
wasm/dist/qsx_scalar.js: wasm/qsx_api.cpp $(DEC_SRC) $(DEC_HDR)
	mkdir -p wasm/dist && $(ENV) em++ $(EMFLAGS) wasm/qsx_api.cpp $(DEC_SRC) -o $@
wasm/dist/qsx_simd.js: wasm/qsx_api.cpp $(DEC_SRC) $(DEC_HDR)
	mkdir -p wasm/dist && $(ENV) em++ $(EMFLAGS) -msimd128 wasm/qsx_api.cpp $(DEC_SRC) -o $@

# ---------------------------------------------------------------- tests / lint
test: test-cpp test-py
test-cpp: $(B)/test_decoder graphs
	QSX_SHOTS=2000 $(B)/test_decoder $(GRAPHS)
test-py: decoders graphs
	$(ENV) PYTHONPATH=$(ROOT) pytest -q tests

lint:
	$(ENV) ruff check .
	$(ENV) for d in 3 5; do \
	  $(PY) sim/qsx_graph.py --d $$d --p 0.001 --weights q5 --out $(B)/graphs/d$${d}_q5.qsxg >/dev/null && \
	  $(PY) rtl/gen_graph.py --graph $(B)/graphs/d$${d}_q5.qsxg --out $(B)/rtl/d$${d}_q5 >/dev/null && \
	  verilator --lint-only -Wall -I$(B)/rtl/d$${d}_q5 $(RTL) --top-module qsx_top || exit 1; done

# ---------------------------------------------------------------- co-simulation (M2)
cosim-quick: decoders
	$(ENV) $(PY) tb/run_cosim.py --distances 3,5 --random 20000 --stim 4000 --chunks 4 --sweep-random 2000 \
	  --top-random 2000 --top-stim 2000 --out $(B)/cosim_quick
cosim: decoders
	$(ENV) $(PY) tb/run_cosim.py --distances 3,5,7

# ---------------------------------------------------------------- formal (M3)
formal-quick:
	$(ENV) cd formal/sva && sby -f ingress.sby && sby -f top.sby stub_prove
	$(ENV) cd formal/tla && java -XX:+UseParallelGC -cp $$TLA2TOOLS tlc2.TLC -workers 8 -deadlock \
	  -metadir $(ROOT)/$(B)/tlc/quick -config MC_main.cfg QSXProtocol.tla | tail -3
formal:
	$(ENV) $(PY) formal/run_formal.py

# ---------------------------------------------------------------- FPGA (M2)
synth:
	$(ENV) $(PY) fpga/run_fpga.py && $(PY) bench/m2_critpath.py

# ---------------------------------------------------------------- experiments
m1: decoders pymatching
	$(ENV) $(PY) bench/m1_baselines.py --weights unweighted,q5 --max-shots 4000000 --target-errors 300
	$(ENV) $(PY) bench/m1_latency.py
m4: native wasm
	$(ENV) $(PY) bench/m4_runtime.py
m6: decoders
	$(ENV) $(PY) learned/adaptive.py
m7:
	$(ENV) $(PY) federated/fed.py --rounds 40 --local-steps 100
m8: decoders
	$(ENV) PYTHONPATH=$(ROOT) pytest -q tests/test_infra.py --junitxml=results/M8/tests.xml && $(PY) bench/m8_overhead.py

m2hw: decoders
	$(ENV) $(PY) bench/m2_hw.py && $(PY) bench/m3_overhead.py --distances 3,5,7
m5:
	$(ENV) $(PY) v8/run_v8_tests.py --mutation && $(PY) v8/bench_anytrue.py
e2e: decoders wasm
	$(ENV) $(PY) bench/e2e_demo.py --max-rounds 6
env:
	$(ENV) $(PY) bench/env_probe.py
viz: wasm
	$(ENV) $(PY) bench/viz_data.py && echo "open http://127.0.0.1:8765/viz/" && $(PY) -m http.server 8765 --bind 127.0.0.1
viz-test: wasm
	$(ENV) $(PY) bench/viz_data.py > /dev/null && ($(PY) -m http.server 8766 --bind 127.0.0.1 > /dev/null 2>&1 & echo $$! > $(B)/viz_srv.pid) \
	  && sleep 1 && mkdir -p $(B)/viz && node viz/smoke.mjs 8766 $(B)/viz; rc=$$?; kill $$(cat $(B)/viz_srv.pid); exit $$rc

figures:
	$(ENV) $(PY) bench/make_figures.py

check-numbers:
	$(ENV) $(PY) bench/check_numbers.py

# ---------------------------------------------------------------- reproduction
# reproduce-quick (< 1 h): rebuild everything, unit/integration tests, reduced experiments into
# build/rq/, quick co-sim + formal, regenerate all figures from results/, cross-check numbers.
reproduce-quick: decoders pymatching native wasm graphs
	$(MAKE) test lint
	$(ENV) $(PY) bench/m1_baselines.py --distances 3,5 --ps 0.002,0.005 --weights q5 --max-shots 200000 \
	  --target-errors 100 --out $(B)/rq/M1
	$(MAKE) cosim-quick formal-quick
	$(ENV) $(PY) bench/m4_runtime.py --distances 5 --shots 20000 --chrome 0 --out $(B)/rq/m4.json
	$(ENV) PYTHONPATH=$(ROOT) pytest -q tests/test_infra.py && $(PY) bench/m8_overhead.py $(B)/rq/m8.json
	$(ENV) $(PY) bench/e2e_demo.py --shots 1000 --max-rounds 6 --out $(B)/rq/e2e.json
	$(MAKE) paper check-numbers
	$(ENV) $(PY) bench/compare_quick.py

reproduce-full: decoders pymatching native wasm graphs
	$(MAKE) test lint m1 cosim formal synth m2hw m4 m5 m6 m7 m8 e2e figures paper check-numbers

paper: figures
	$(ENV) $(PY) bench/claims.py > /dev/null && cd paper && tectonic -X compile qshieldx.tex

ci: lint test cosim-quick formal-quick

clean:
	rm -rf $(B)
