# FuzzBench Architecture

## Experiment Execution Flow

### Entry Point
`experiment/run_experiment.py` — parses CLI args (fuzzers, benchmarks, trials, config yaml), validates config, then starts a **dispatcher container**.

### Dispatcher Container
Image: `{docker_registry}/dispatcher-image`

The dispatcher container runs `experiment/dispatcher.py`, which:
1. Initializes database (SQLite for local, Postgres for cloud)
2. Builds images: calls `builder.build_all_measurers()` and `builder.build_all_fuzzer_benchmarks()` to create runner docker images
3. Creates trial records in the database
4. Launches two main concurrent components:
   - **Scheduler thread** (`experiment/scheduler.py` → `schedule_loop`)
   - **Measurer process** (`experiment/measurer/measure_manager.py` → `measure_main`)
5. Periodically generates reports via `reporter.output_report`

### Scheduler (`experiment/scheduler.py`)
- Runs `schedule_loop()` in a thread inside the dispatcher
- Queries DB for pending/running/expired trials
- For each pending trial, calls `create_trial_instance()` which:
  - Renders `experiment/resources/runner-startup-script-template.sh` (Jinja2)
  - Starts a **runner container** via `gcloud.create_instance` (cloud) or `docker run` (local)
- Manages preempted trials (cloud only), core allocation (local)

### Runner Container
Image: `{docker_registry}/runners/{fuzzer}/{benchmark}:{tag}` (tag=`latest` for local, experiment name for cloud)

Each runner container (`experiment/runner.py`):
- Sets up seed corpus
- Runs the fuzzer's `fuzz()` function in a thread
- Periodically archives corpus and syncs results to filestore

### Measurer (`experiment/measurer/measure_manager.py`)
- Runs as a separate process inside the dispatcher
- Periodically measures code coverage by pulling corpus archives from filestore
- Stores measurement results in the database

### Runner Startup Script Template
`experiment/resources/runner-startup-script-template.sh` — rendered by the scheduler, does `docker run` with environment variables (FUZZER, BENCHMARK, TRIAL_ID, MAX_TOTAL_TIME, etc.).

### Key Config (fuzzbench.yaml)
- `docker_registry`: where images are stored (e.g. `gcr.io/fuzzbench`)
- `experiment_filestore` / `report_filestore`: data storage paths
- `trials`: number of trials per fuzzer-benchmark pair
- `max_total_time`: seconds each trial runs
- `local_experiment`: true for local runs

### Docker Image URL Pattern
- Runner: `{docker_registry}/runners/{fuzzer}/{benchmark}:latest`
- Builder: `{docker_registry}/builders/{fuzzer}/{benchmark}`

## 重构计划

sqlite数据库架构完全不变。

简化架构：
- 不要先run_experiment.py脚本启动dispatcher，里面再启动scheduler，然后再启动各个runner。而是直接run_experiment.py启动启动各个runner，同时支持现在的cpuset调度。
- 其次，不要同时跑measurer线程，而是完全不启动measurer。改用专门一个脚本run_measurer.py，去多线程构建measurer镜像，自动去找到没有测量过的corpus压缩包去跑measurer，测量后主动直接存入数据库或者在experiment filestore生成相应的文件。最终experiment filestore的形式也完全相同。整个measure过程放到runner跑完之后。
