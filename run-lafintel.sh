#!/bin/bash

# 对比原版afl和lafintel，在sqlite3_ossfuzz上，跑2h。

SCRIPTPATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

cd $SCRIPTPATH

BENCHNAME=lafintel-exp-1

# libafl_libfuzzer bad benchmarks

source .venv/bin/activate

# make test-run-afl-freetype2_ftfuzzer

PYTHONPATH=. python3 experiment/run_experiment.py \
--experiment-config $SCRIPTPATH/fuzzbench.yaml \
--benchmarks sqlite3_ossfuzz \
--experiment-name $BENCHNAME \
--fuzzers afl lafintel
