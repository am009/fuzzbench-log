#!/bin/bash

SCRIPTPATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

set -e

# Default values
EXPERIMENT_NAME=""
BENCHMARKS=""
FUZZERS=""

# Function to show usage
usage() {
    echo "Usage: $0 -n <experiment_name> -b <benchmarks> -f <fuzzers>"
    echo ""
    echo "Options:"
    echo "  -n, --name       Experiment name (required)"
    echo "  -b, --benchmarks Space-separated list of benchmarks (required)"
    echo "  -f, --fuzzers    Space-separated list of fuzzers (required)"
    echo "  -h, --help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -n my-experiment -b 'openssl_x509 proj4_proj_crs_to_crs_fuzzer' -f 'honggfuzz afl'"
    echo "  $0 --name test-run --benchmarks 'bloaty_fuzz_target freetype2_ftfuzzer' --fuzzers 'libfuzzer'"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--name)
            EXPERIMENT_NAME="$2"
            shift 2
            ;;
        -b|--benchmarks)
            BENCHMARKS="$2"
            shift 2
            ;;
        -f|--fuzzers)
            FUZZERS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Check required arguments
if [[ -z "$EXPERIMENT_NAME" ]]; then
    echo "Error: Experiment name is required"
    usage
fi

if [[ -z "$BENCHMARKS" ]]; then
    echo "Error: Benchmarks are required"
    usage
fi

if [[ -z "$FUZZERS" ]]; then
    echo "Error: Fuzzers are required"
    usage
fi

# Convert space-separated strings to arrays
read -ra BENCHMARK_ARRAY <<< "$BENCHMARKS"
read -ra FUZZER_ARRAY <<< "$FUZZERS"

# Validate that we have at least one benchmark and fuzzer
if [[ ${#BENCHMARK_ARRAY[@]} -eq 0 ]]; then
    echo "Error: At least one benchmark must be specified"
    exit 1
fi

if [[ ${#FUZZER_ARRAY[@]} -eq 0 ]]; then
    echo "Error: At least one fuzzer must be specified"
    exit 1
fi

# Display configuration
echo "Experiment Configuration:"
echo "  Name: $EXPERIMENT_NAME"
echo "  Benchmarks: ${BENCHMARK_ARRAY[*]}"
echo "  Fuzzers: ${FUZZER_ARRAY[*]}"
echo ""

# Wait for docker and prepare benchmark
# /sn640/fuzzerlog/wait-docker.sh || exit 1
$SCRIPTPATH/wait-docker-fuzzbench.sh || exit 1
# /home/wjk/benchmark-prepare.sh || exit 1

cd $SCRIPTPATH
source .venv/bin/activate

# Build the experiment command
EXPERIMENT_CMD="PYTHONPATH=. python3 experiment/run_experiment.py"
EXPERIMENT_CMD="$EXPERIMENT_CMD --experiment-config $SCRIPTPATH/fuzzbench.yaml"
EXPERIMENT_CMD="$EXPERIMENT_CMD --experiment-name $EXPERIMENT_NAME"
EXPERIMENT_CMD="$EXPERIMENT_CMD --benchmarks ${BENCHMARK_ARRAY[*]}"
EXPERIMENT_CMD="$EXPERIMENT_CMD --fuzzers ${FUZZER_ARRAY[*]}"
EXPERIMENT_CMD="$EXPERIMENT_CMD --allow-uncommitted-changes"

echo "Running command:"
echo "$EXPERIMENT_CMD"
echo ""

# Execute the experiment
eval "$EXPERIMENT_CMD"


# Restore benchmark
# /home/wjk/benchmark-restore.sh || exit 1

# sudo chown -R wjk:wjk /sn640/fuzzerlog/experiment-data/$EXPERIMENT_NAME
