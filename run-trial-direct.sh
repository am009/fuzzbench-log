#!/bin/bash
# Simplified FuzzBench runner: directly pull and start runner containers.
# Skips the dispatcher/scheduler/measurer architecture entirely.

set -e

SCRIPTPATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

# Defaults
EXPERIMENT_NAME=""
BENCHMARKS=""
FUZZERS=""
TRIALS=1
DOCKER_REGISTRY="gcr.io/fuzzbench"
MAX_TOTAL_TIME=82800
SNAPSHOT_PERIOD=900
EXPERIMENT_FILESTORE="/home/user/experiment-data"
CPUS_PER_RUNNER=1
TAG="latest"

usage() {
    echo "Usage: $0 -n <name> -b <benchmarks> -f <fuzzers> [options]"
    echo ""
    echo "Required:"
    echo "  -n, --name          Experiment name"
    echo "  -b, --benchmarks    Space-separated list of benchmarks"
    echo "  -f, --fuzzers       Space-separated list of fuzzers"
    echo ""
    echo "Optional:"
    echo "  -t, --trials        Number of trials per fuzzer-benchmark pair (default: 1)"
    echo "  -r, --registry      Docker registry (default: gcr.io/fuzzbench)"
    echo "  -T, --time          Max total time in seconds (default: 82800)"
    echo "  -s, --snapshot      Snapshot period in seconds (default: 900)"
    echo "  -c, --cpus          CPUs per runner container (default: 1)"
    echo "  --tag               Docker image tag (default: latest)"
    echo "  --filestore         Experiment filestore path (default: /home/user/experiment-data)"
    echo "  -h, --help          Show this help message"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--name)       EXPERIMENT_NAME="$2"; shift 2 ;;
        -b|--benchmarks) BENCHMARKS="$2"; shift 2 ;;
        -f|--fuzzers)    FUZZERS="$2"; shift 2 ;;
        -t|--trials)     TRIALS="$2"; shift 2 ;;
        -r|--registry)   DOCKER_REGISTRY="$2"; shift 2 ;;
        -T|--time)       MAX_TOTAL_TIME="$2"; shift 2 ;;
        -s|--snapshot)   SNAPSHOT_PERIOD="$2"; shift 2 ;;
        -c|--cpus)       CPUS_PER_RUNNER="$2"; shift 2 ;;
        --tag)           TAG="$2"; shift 2 ;;
        --filestore)     EXPERIMENT_FILESTORE="$2"; shift 2 ;;
        -h|--help)       usage ;;
        *)               echo "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$EXPERIMENT_NAME" || -z "$BENCHMARKS" || -z "$FUZZERS" ]]; then
    echo "Error: --name, --benchmarks, and --fuzzers are required"
    usage
fi

read -ra BENCHMARK_ARRAY <<< "$BENCHMARKS"
read -ra FUZZER_ARRAY <<< "$FUZZERS"

echo "=== Direct Trial Runner ==="
echo "  Experiment:  $EXPERIMENT_NAME"
echo "  Registry:    $DOCKER_REGISTRY"
echo "  Benchmarks:  ${BENCHMARK_ARRAY[*]}"
echo "  Fuzzers:     ${FUZZER_ARRAY[*]}"
echo "  Trials:      $TRIALS"
echo "  Max time:    ${MAX_TOTAL_TIME}s"
echo "  CPUs/runner: $CPUS_PER_RUNNER"
echo ""

# Create filestore directories
mkdir -p "$EXPERIMENT_FILESTORE"

# Persistent trial ID counter: read from file, increment per trial, write back
TRIAL_ID_FILE="${EXPERIMENT_FILESTORE}/trial_id_counter"
if [[ -f "$TRIAL_ID_FILE" ]]; then
    TRIAL_ID=$(cat "$TRIAL_ID_FILE")
else
    TRIAL_ID=0
fi

for FUZZER in "${FUZZER_ARRAY[@]}"; do
    for BENCHMARK in "${BENCHMARK_ARRAY[@]}"; do
        IMAGE="${DOCKER_REGISTRY}/runners/${FUZZER}/${BENCHMARK}:${TAG}"

        # Read fuzz_target from benchmark.yaml
        BENCHMARK_YAML="${SCRIPTPATH}/benchmarks/${BENCHMARK}/benchmark.yaml"
        FUZZ_TARGET=$(grep '^fuzz_target:' "$BENCHMARK_YAML" | sed 's/^fuzz_target: *//')
        if [[ -z "$FUZZ_TARGET" ]]; then
            echo "ERROR: fuzz_target not found in $BENCHMARK_YAML, skipping"
            continue
        fi

        echo "Pulling image: $IMAGE"
        docker pull "$IMAGE" || { echo "ERROR: Failed to pull $IMAGE, skipping"; continue; }

        for ((T=0; T<TRIALS; T++)); do
            TRIAL_ID=$((TRIAL_ID + 1))
            echo "$TRIAL_ID" > "$TRIAL_ID_FILE"
            CONTAINER_NAME="runner-${EXPERIMENT_NAME}-${FUZZER}-${BENCHMARK}-t${T}"

            echo "Starting trial $TRIAL_ID: fuzzer=$FUZZER benchmark=$BENCHMARK trial=$T"

            docker run \
                --privileged --cpus="$CPUS_PER_RUNNER" \
                -d --rm \
                -e INSTANCE_NAME="$CONTAINER_NAME" \
                -e FUZZER="$FUZZER" \
                -e BENCHMARK="$BENCHMARK" \
                -e EXPERIMENT="$EXPERIMENT_NAME" \
                -e TRIAL_ID="$TRIAL_ID" \
                -e MICRO_EXPERIMENT=False \
                -e MAX_TOTAL_TIME="$MAX_TOTAL_TIME" \
                -e SNAPSHOT_PERIOD="$SNAPSHOT_PERIOD" \
                -e NO_SEEDS=False \
                -e NO_DICTIONARIES=False \
                -e OSS_FUZZ_CORPUS=False \
                -e CUSTOM_SEED_CORPUS_DIR= \
                -e DOCKER_REGISTRY="$DOCKER_REGISTRY" \
                -e EXPERIMENT_FILESTORE="$EXPERIMENT_FILESTORE" \
                -e FUZZ_TARGET="$FUZZ_TARGET" \
                -e PRIVATE=False \
                -e LOCAL_EXPERIMENT=True \
                -v "${EXPERIMENT_FILESTORE}:${EXPERIMENT_FILESTORE}" \
                --shm-size=2g \
                --cap-add SYS_NICE --cap-add SYS_PTRACE \
                --security-opt seccomp=unconfined \
                --name="$CONTAINER_NAME" \
                "$IMAGE" && echo "  -> Container: $CONTAINER_NAME" || echo "  -> FAILED to start: $CONTAINER_NAME"
        done
    done
done

echo ""
echo "=== All trial containers launched ==="
echo "Monitor with: docker ps --filter name=runner-${EXPERIMENT_NAME}"
echo "Logs:         docker logs -f <container_name>"
