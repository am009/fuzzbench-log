#!/bin/bash


# DEBUGPY_FUZZBENCH_DISPATCHER=1 
PYTHONPATH=. FIX_MEASURE=82800 python3 experiment/run_experiment.py --concurrent-builds 3 --measurers-cpus 2 --runners-cpus 30 --experiment-config ./fuzzbench.yaml --experiment-name latest-10bench-2 --benchmarks bloaty_fuzz_target openssl_x509 proj4_proj_crs_to_crs_fuzzer freetype2_ftfuzzer lcms_cms_transform_fuzzer curl_curl_fuzzer_http harfbuzz_hb-shape-fuzzer libjpeg-turbo_libjpeg_turbo_fuzzer libpcap_fuzz_both sqlite3_ossfuzz --fuzzers aflplusplus_latest honggfuzz_latest libafl_latest --allow-uncommitted-changes
