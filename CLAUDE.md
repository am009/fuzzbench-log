# FuzzBench Architecture (Refactored)

## Experiment Execution Flow

### Entry Point
`experiment/run_experiment.py` — parses CLI args (fuzzers, benchmarks, trials, config yaml), validates config, then **directly** builds images, creates DB records, and launches runner containers. No dispatcher or scheduler containers involved.

Flow:
1. Reads and validates config (yaml + CLI args)
2. Sets environment variables (`setup_environment()`)
3. Initializes SQLite database
4. Creates Experiment record in DB
5. Builds runner images via `experiment/dispatcher.build_images_for_trials()`
6. Creates Trial records in DB
7. Launches all runners via `run_all_trials()` with cpuset-based scheduling (optional)
8. Records experiment end time

### Runner Scheduling (`run_all_trials`)
- When `--runners-cpus` is provided, uses cpuset allocation: divides available CPUs into slots of `runner_num_cpu_cores` each, passes cpuset ranges to docker
- When `--no-cpuset` is used, launches all trials concurrently with only `--cpus` limiting (no cpuset pinning)
- When neither `--runners-cpus` nor `--no-cpuset`, all trials launch at once with no CPU limits beyond `--cpus`

### Runner Container
Image: `{docker_registry}/runners/{fuzzer}/{benchmark}:latest`

Each runner container (`experiment/runner.py`):
- Sets up seed corpus
- Runs the fuzzer's `fuzz()` function in a thread
- Periodically archives corpus and syncs results to filestore

### Startup Script Template
`experiment/resources/runner-startup-script-template.sh` — rendered via Jinja2 by `experiment/scheduler.render_startup_script_template()`, does `docker run` with environment variables (FUZZER, BENCHMARK, TRIAL_ID, MAX_TOTAL_TIME, etc.).

### Measurer (separate step)
`experiment/run_measurer.py` — runs **after** all trials complete. Multi-threaded: builds measurer images, finds unmeasured corpus archives, measures coverage, stores results in DB.

### Key Config (fuzzbench.yaml)
- `docker_registry`: where images are stored
- `experiment_filestore` / `report_filestore`: data storage paths
- `trials`: number of trials per fuzzer-benchmark pair
- `max_total_time`: seconds each trial runs
- `local_experiment`: true for local runs
- `runner_num_cpu_cores`: CPU cores per runner container (used for docker `--cpus`)

### Docker Image URL Pattern
- Runner: `{docker_registry}/runners/{fuzzer}/{benchmark}:latest`
- Builder: `{docker_registry}/builders/{fuzzer}/{benchmark}`
