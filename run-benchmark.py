#!/usr/bin/env python3
"""
Schedule and run fuzzbench trials for one or more benchmarks.

Usage:
    python3 run-benchmark.py <benchmark> [benchmark ...] <max_parallel> [--experiment <name>]

For each fuzzer, checks how many trials have already completed (across all
experiment directories).  If fewer than REQUIRED_TRIALS, launches new trials
up to the limit, respecting the max_parallel concurrency cap.

Each trial:
  1. docker pull the runner image
  2. docker run  (foreground, blocking)
  3. gen-coverage-standalone.sh to produce seed_stats.json
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import threading
import time
import yaml
import filelock

# ── Global configuration ────────────────────────────────────────────────────

script_path = os.path.realpath(__file__)
script_dir = os.path.dirname(script_path)

DEBUG=True

REQUIRED_TRIALS = 5

DOCKER_REGISTRY = "wjk-pc-registry.fancybag.cn/fuzzbench"
DOCKER_TAG = "latest"
MAX_TOTAL_TIME = 82800
SNAPSHOT_PERIOD = 900
CPUS_PER_RUNNER = 1
EXPERIMENT_FILESTORES = [
    f"{script_dir}/../experiment-data",
]
EXPERIMENT_FILESTORE = EXPERIMENT_FILESTORES[0]  # where new trials are stored
FUZZBENCH_DIR = script_dir
GEN_COVERAGE_SCRIPT = f"{script_dir}/../fuzzer-log-processor/gen-coverage-standalone.sh"

# ── All fuzzers (from scheduler/exp-run.sh) ─────────────────────────────────

HFUZZ_CORE = [
    "honggfuzz_latest", "honggfuzz_log", "honggfuzz_no_bin",
    "honggfuzz_sched_no_short", "honggfuzz_sched_no_cov",
    "honggfuzz_sched_no_faster", "honggfuzz_no_mopt",
    "honggfuzz_mut_no_cmplog", "honggfuzz_mut_no_dyn_dict",
]
AFLPP_CORE = [
    "aflplusplus_latest", "aflplusplus_log", "aflplusplus_mopt",
    "aflplusplus_mut_no_cmplog", "aflplusplus_no_bin",
    "aflplusplus_sched_no_short", "aflplusplus_sched_no_cov",
    "aflplusplus_sched_no_faster",
]
LIBAFL_CORE = [
    "libafl_latest", "libafl_log", "libafl_no_bin",
    "libafl_sched_no_short", "libafl_sched_no_cov",
    "libafl_sched_no_faster", "libafl_no_mopt",
]

HFUZZ_MUT = [
    "honggfuzz_mut_no_bitflip", "honggfuzz_mut_no_arith",
    "honggfuzz_mut_no_interesting", "honggfuzz_mut_no_dict_extra",
    "honggfuzz_mut_no_random_bytes", "honggfuzz_mut_no_structural_bytes",
    "honggfuzz_mut_no_ascii_num", "honggfuzz_mut_no_splice",
]
AFLPP_MUT = [
    "aflplusplus_mut_no_bitflip", "aflplusplus_mut_no_arith",
    "aflplusplus_mut_no_interesting", "aflplusplus_mut_no_dict_extra",
    "aflplusplus_mut_no_random_bytes", "aflplusplus_mut_no_structural",
    "aflplusplus_mut_no_ascii_num", "aflplusplus_mut_no_splice",
]
LIBAFL_MUT = [
    "libafl_mut_no_bitflip", "libafl_mut_no_arith",
    "libafl_mut_no_interesting", "libafl_mut_no_dict_extra",
    "libafl_mut_no_cmplog", "libafl_mut_no_random_bytes",
    "libafl_mut_no_structural_bytes", "libafl_mut_no_splice",
]

ALL_FUZZERS = (
    HFUZZ_CORE + HFUZZ_MUT +
    AFLPP_CORE + AFLPP_MUT +
    LIBAFL_CORE + LIBAFL_MUT
)

# ── Helpers ──────────────────────────────────────────────────────────────────

libfuzzerlog_path = os.path.join(script_dir, "libfuzzerlog.so")

def count_existing_trials(benchmark: str, fuzzer: str) -> int:
    """Count successful trials for a benchmark-fuzzer combo across all experiment stores."""
    total = 0
    for store in EXPERIMENT_FILESTORES:
        pattern = os.path.join(
            store, "*/experiment-folders",
            f"{benchmark}-{fuzzer}", "trial-*",
        )
        for trial_dir in glob.glob(pattern):
            if not os.path.isdir(trial_dir):
                continue
            archive_path = os.path.join(
                trial_dir, "corpus", "corpus-archive-0090.tar.gz"
            )
            if os.path.isfile(archive_path):
                total += 1
    return total


def get_fuzz_target(benchmark: str) -> str:
    """Read fuzz_target from benchmark.yaml."""
    yaml_path = os.path.join(FUZZBENCH_DIR, "benchmarks", benchmark, "benchmark.yaml")
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data["fuzz_target"]


def next_trial_id() -> int:
    """Atomically increment and return the next global trial ID."""
    id_file = os.path.join(EXPERIMENT_FILESTORE, "trial_id_counter")
    lock_file = id_file + ".lock"
    lock = filelock.FileLock(lock_file)
    with lock:
        if os.path.exists(id_file):
            with open(id_file) as f:
                tid = int(f.read().strip())
        else:
            tid = 0
        tid += 1
        with open(id_file, "w") as f:
            f.write(str(tid))
    return tid


def run_trial(benchmark: str, fuzzer: str, fuzz_target: str,
              experiment_name: str, semaphore: threading.Semaphore):
    """Pull image, run docker container (blocking), then generate coverage."""
    trial_id = next_trial_id()
    image = f"{DOCKER_REGISTRY}/runners/{fuzzer}/{benchmark}:{DOCKER_TAG}"
    container_name = f"runner-{trial_id}"

    tag = f"[{fuzzer}/{benchmark} trial={trial_id}]"

    with semaphore:
        print(f"{tag} Acquired slot, starting...")

        # ── 1. docker pull ───────────────────────────────────────────────
        print(f"{tag} Pulling {image}")
        ret = subprocess.run(["docker", "pull", image],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ret.returncode != 0:
            print(f"{tag} ERROR pulling image")
            return

        # ── 1.5. Set up fuse-zstd compressed results directory ──────────
        trial_dir = os.path.join(
            EXPERIMENT_FILESTORE, experiment_name, "experiment-folders",
            f"{benchmark}-{fuzzer}", f"trial-{trial_id}",
        )
        results_dir = os.path.join(trial_dir, "log")
        results_data_dir = os.path.join(trial_dir, "log-data")
        os.makedirs(results_dir, exist_ok=True)
        os.makedirs(results_data_dir, exist_ok=True)

        print(f"{tag} Mounting fuse-zstd: {results_dir} -> {results_data_dir}")
        fuse_proc = subprocess.Popen(
            ["fuse-zstd",
             "--mount-point", results_dir,
             "--data-dir", results_data_dir,
             "-c", "1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Give fuse-zstd a moment to initialize the mount
        time.sleep(1)
        if fuse_proc.poll() is not None:
            print(f"{tag} ERROR: fuse-zstd exited early with code {fuse_proc.returncode}")
            return

        # ── 2. docker run -i and stream logs to the trial directory ──────
        try:
            print(f"{tag} Starting container {container_name}")
            docker_log_path = os.path.join(trial_dir, "docker.log")
            commands = [
                "docker", "run",
                "--privileged", f"--cpus={CPUS_PER_RUNNER}",
                "-i", "--rm",
                "-e", f"INSTANCE_NAME={container_name}",
                "-e", f"FUZZER={fuzzer}",
                "-e", f"BENCHMARK={benchmark}",
                "-e", f"EXPERIMENT={experiment_name}",
                "-e", f"TRIAL_ID={trial_id}",
                "-e", "MICRO_EXPERIMENT=False",
                "-e", f"MAX_TOTAL_TIME={MAX_TOTAL_TIME}",
                "-e", f"SNAPSHOT_PERIOD={SNAPSHOT_PERIOD}",
                "-e", "NO_SEEDS=False",
                "-e", "NO_DICTIONARIES=False",
                "-e", "OSS_FUZZ_CORPUS=False",
                "-e", "CUSTOM_SEED_CORPUS_DIR=",
                "-e", f"DOCKER_REGISTRY={DOCKER_REGISTRY}",
                "-e", f"EXPERIMENT_FILESTORE={EXPERIMENT_FILESTORE}",
                "-e", f"FUZZ_TARGET={fuzz_target}",
                "-e", "PRIVATE=False",
                "-e", "LOCAL_EXPERIMENT=True",
                "-v", f"{EXPERIMENT_FILESTORE}:{EXPERIMENT_FILESTORE}",
                "-e", f"FUZZER_LOG_FILE={results_dir}/fuzzerlog.txt",
                "-v", f"{libfuzzerlog_path}:/usr/local/lib/libfuzzerlog.so",
                "-v", f"{script_dir}/experiment/runner.py:/src/experiment/runner.py", # TODO
                "--shm-size=2g",
                "--cap-add", "SYS_NICE",
                "--cap-add", "SYS_PTRACE",
                "--security-opt", "seccomp=unconfined",
                "--name", container_name,
                image,
            ]
            if DEBUG:
                print(' '.join(commands))
            with open(docker_log_path, "wb") as docker_log:
                ret = subprocess.run(
                    commands,
                    stdout=docker_log,
                    stderr=docker_log,
                )

            if ret.returncode != 0:
                print(f"{tag} ERROR container exited with code {ret.returncode}, see {docker_log_path}")
                return

            print(f"{tag} Container finished successfully, log saved to {docker_log_path}.")

            # ── 3. gen-coverage-standalone.sh ────────────────────────────
            if not os.path.exists(GEN_COVERAGE_SCRIPT):
                print(f"{tag} WARNING: gen coverage script not found at {GEN_COVERAGE_SCRIPT}, skipping coverage.")
            else:
                corpus_path = os.path.join(
                    EXPERIMENT_FILESTORE, experiment_name, "experiment-folders",
                    f"{benchmark}-{fuzzer}", f"trial-{trial_id}", "corpus",
                )
                if os.path.isdir(corpus_path):
                    print(f"{tag} Generating coverage for {corpus_path}")
                    coverage_log_path = os.path.join(corpus_path, "gen-coverage.log")
                    with open(coverage_log_path, "wb") as coverage_log:
                        ret = subprocess.run(
                            [GEN_COVERAGE_SCRIPT, FUZZBENCH_DIR, corpus_path],
                            stdout=coverage_log, stderr=coverage_log,
                        )
                    if ret.returncode != 0:
                        print(f"{tag} ERROR generating coverage, see {coverage_log_path}")
                    else:
                        print(f"{tag} Coverage generated, log saved to {coverage_log_path}.")
                else:
                    print(f"{tag} WARNING: corpus not found at {corpus_path}, skipping coverage.")
        finally:
            # ── 4. Stop fuse-zstd and unmount ────────────────────────────
            print(f"{tag} Stopping fuse-zstd and unmounting {results_dir}")
            fuse_proc.terminate()
            try:
                fuse_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                fuse_proc.kill()
                fuse_proc.wait()
            # Ensure the FUSE mount is fully released
            subprocess.run(["fusermount", "-u", results_dir],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"{tag} Done, slot released.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run fuzzbench trials for one or more benchmarks until each fuzzer has enough trials.")
    parser.add_argument("benchmarks", nargs="+", help="Benchmark name(s) (e.g. bloaty_fuzz_target)")
    parser.add_argument("--max-parallel", "-p", type=int, required=True,
                        help="Maximum number of concurrent trials")
    parser.add_argument("--experiment", "-e", default="auto",
                        help="Experiment name (default: auto-<benchmark>)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show trial counts, do not run anything")
    parser.add_argument("--skip-check", action="store_true",
                        help="Skip pre-flight check for running runner containers")
    args = parser.parse_args()

    max_parallel = args.max_parallel

    # ── Dependency checks ─────────────────────────────────────────────
    if not shutil.which("fuse-zstd"):
        print("ERROR: 'fuse-zstd' command not found. Please download and install it:")
        print("  wget https://github.com/am009/fuzzbench-log/releases/download/260312/fuse-zstd_1.2.0-1_amd64.deb")
        print("  sudo dpkg -i fuse-zstd_1.2.0-1_amd64.deb")
        sys.exit(1)

    if not os.path.exists(libfuzzerlog_path):
        print(f"libfuzzerlog.so not found at {libfuzzerlog_path}, downloading...")
        url = "https://github.com/am009/fuzzbench-log/releases/download/260312/libfuzzerlog.so"
        subprocess.run(["wget", "-O", libfuzzerlog_path, url], check=True)

    # ── Pre-flight checks (once, before any benchmark) ────────────────
    if not args.skip_check:
        ret = subprocess.run(
            ["docker", "ps", "--filter", "name=runner-", "--format", "{{.Names}}"],
            capture_output=True, text=True,
        )
        running_containers = [c for c in ret.stdout.strip().splitlines() if c]
        if running_containers:
            print(f"ERROR: {len(running_containers)} fuzzbench runner container(s) already running:")
            for c in running_containers:
                print(f"  {c}")
            print("Please stop them before starting new trials.")
            sys.exit(1)

    os.makedirs(EXPERIMENT_FILESTORE, exist_ok=True)

    for benchmark in args.benchmarks:
        print(f"\n{'='*60}")
        print(f"Benchmark: {benchmark}")
        print(f"{'='*60}")

        experiment_name = args.experiment
        if experiment_name == "auto":
            base = f"auto-{benchmark}"
            experiment_name = base
            suffix = 2
            while any(
                os.path.exists(os.path.join(store, experiment_name))
                for store in EXPERIMENT_FILESTORES
            ):
                experiment_name = f"{base}-{suffix}"
                suffix += 1

        # Validate benchmark
        benchmark_yaml = os.path.join(FUZZBENCH_DIR, "benchmarks", benchmark, "benchmark.yaml")
        if not os.path.exists(benchmark_yaml):
            print(f"ERROR: benchmark.yaml not found at {benchmark_yaml}, skipping.")
            continue

        fuzz_target = get_fuzz_target(benchmark)
        print(f"Fuzz target:    {fuzz_target}")
        print(f"Experiment:     {experiment_name}")
        print(f"Max parallel:   {max_parallel}")
        print(f"Required trials per fuzzer: {REQUIRED_TRIALS}")
        print()

        # ── Count existing trials and build work list ────────────────────
        tasks = []  # list of (fuzzer, needed_count)
        for fuzzer in ALL_FUZZERS:
            existing = count_existing_trials(benchmark, fuzzer)
            needed = REQUIRED_TRIALS - existing
            status = "OK" if needed <= 0 else f"need {needed} more"
            print(f"  {fuzzer:50s}  existing={existing}  {status}")
            if needed > 0:
                tasks.append((fuzzer, needed))

        total_new = sum(n for _, n in tasks)
        print(f"\nTotal new trials to run: {total_new}")
        if total_new == 0 or args.dry_run:
            if total_new == 0:
                print("All fuzzers have enough trials. Nothing to do.")
            continue

        # ── Launch threads ───────────────────────────────────────────────
        semaphore = threading.Semaphore(max_parallel)
        threads = []

        for fuzzer, needed in tasks:
            for _ in range(needed):
                t = threading.Thread(
                    target=run_trial,
                    args=(benchmark, fuzzer, fuzz_target, experiment_name, semaphore),
                    daemon=True,
                )
                t.start()
                threads.append(t)
                time.sleep(0.1)  # slight stagger to avoid pull stampede

        print(f"\nLaunched {len(threads)} trial threads. Waiting for completion...")
        for t in threads:
            t.join()

        print(f"\nAll trials for {benchmark} completed.")

    print("\nAll benchmarks done.")


if __name__ == "__main__":
    main()
