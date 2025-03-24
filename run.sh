#!/bin/bash

SCRIPTPATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

cd $SCRIPTPATH

BENCHNAME=proj7-24h

# libafl_libfuzzer bad benchmarks

source .venv/bin/activate

# make test-run-afl-freetype2_ftfuzzer

PYTHONPATH=. python3 experiment/run_experiment.py \
--experiment-config $SCRIPTPATH/fuzzbench.yaml \
--benchmarks proj4_proj_crs_to_crs_fuzzer \
--experiment-name $BENCHNAME \
--fuzzers aflplusplus honggfuzz
