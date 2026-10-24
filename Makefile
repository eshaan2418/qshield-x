# QShield-X top-level Makefile. Run `source env.sh` first (or use `make` targets, which source it).
SHELL := /bin/bash
ROOT  := $(abspath .)
ENV   := source $(ROOT)/env.sh &&
PY    := $(ROOT)/.venv/bin/python
CXX   ?= clang++
CXXFLAGS ?= -std=c++17 -O3 -Wall -Wextra -Idecoders/include
B     := build
DISTANCES ?= 3 5 7 9

DEC_SRC := decoders/src/decoder.cpp
DEC_HDR := decoders/include/qsx/decoder.hpp
PYEXT   := $(shell $(PY) -c "import sysconfig;print(sysconfig.get_config_var('EXT_SUFFIX'))" 2>/dev/null)

.PHONY: all graphs decoders test test-cpp test-py lint cosim formal synth reproduce-quick reproduce-full paper ci clean

all: decoders graphs

$(B) $(B)/graphs:
	mkdir -p $@

# ---------------------------------------------------------------- graphs
GRAPHS := $(foreach d,$(DISTANCES),$(B)/graphs/d$(d).qsxg)
graphs: $(GRAPHS)
$(B)/graphs/d%.qsxg: sim/qsx_graph.py | $(B)/graphs
	$(PY) sim/qsx_graph.py --d $* --p 0.001 --out $@

# ---------------------------------------------------------------- decoders
decoders: $(B)/qsx_decode $(B)/test_decoder $(B)/qsxdec$(PYEXT)
$(B)/qsx_decode: $(DEC_SRC) $(DEC_HDR) decoders/src/qsx_decode_main.cpp | $(B)
	$(CXX) $(CXXFLAGS) $(DEC_SRC) decoders/src/qsx_decode_main.cpp -o $@
$(B)/test_decoder: $(DEC_SRC) $(DEC_HDR) decoders/tests/test_decoder.cpp | $(B)
	$(CXX) $(CXXFLAGS) -O2 $(DEC_SRC) decoders/tests/test_decoder.cpp -o $@
$(B)/qsxdec$(PYEXT): $(DEC_SRC) $(DEC_HDR) decoders/src/pybind.cpp | $(B)
	$(CXX) $(CXXFLAGS) -shared -fPIC -undefined dynamic_lookup $$($(PY) -m pybind11 --includes) \
	  $(DEC_SRC) decoders/src/pybind.cpp -o $@

# ---------------------------------------------------------------- tests
test: test-cpp test-py
test-cpp: $(B)/test_decoder graphs
	QSX_SHOTS=2000 $(B)/test_decoder $(GRAPHS)
test-py: decoders graphs
	$(ENV) PYTHONPATH=$(ROOT)/$(B):$(ROOT) pytest -q tests

lint:
	$(ENV) ruff check .

clean:
	rm -rf $(B)
