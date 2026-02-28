# FuzzBench SQLite 数据库 Schema 文档

## 数据库概述

- **数据库文件名**: `local.db`
- **存放路径**: `<experiment_filestore>/local.db`
  - 例如：`/home/user/experiment-data/local.db`
- **数据库类型**: SQLite（本地实验）/ PostgreSQL（云端实验）
- **连接方式**: 通过环境变量 `SQL_DATABASE_URL` 配置，本地实验时自动设置为：
  ```
  sqlite:///<experiment_filestore>/local.db?check_same_thread=False
  ```
- **ORM框架**: SQLAlchemy（定义在 `database/models.py`）
- **数据库初始化**: 本地实验时通过 `models.Base.metadata.create_all(db_utils.engine)` 自动建表（见 `experiment/dispatcher.py:161`）

---

## 表结构

数据库共包含 **4 张表**：`experiment`、`trial`、`snapshot`、`crash`。

### 1. `experiment` 表 — 实验元信息

存储每次实验运行的基本信息。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `name` | String | **PRIMARY KEY**, NOT NULL | 实验名称，唯一标识一次实验 |
| `time_created` | DateTime | 默认 `now()` | 实验创建时间 |
| `time_ended` | DateTime | 可为 NULL | 实验结束时间 |
| `git_hash` | String | 可为 NULL | 实验运行时的 git commit hash |
| `private` | Boolean | NOT NULL, 默认 False | 实验是否为私有 |
| `experiment_filestore` | String | 可为 NULL | 实验文件存储路径 |
| `description` | UnicodeText | 可为 NULL | 实验描述 |

**作用**：记录一次完整实验的全局信息，包括何时创建、何时结束、对应的代码版本等。

---

### 2. `trial` 表 — 试验（单次 fuzzer+benchmark 运行）

每个 trial 代表一次具体的 fuzzer 在某个 benchmark 上的运行。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | **PRIMARY KEY**, 自增 | 试验唯一 ID |
| `fuzzer` | String | NOT NULL | fuzzer 名称（如 `aflplusplus`、`libafl`） |
| `experiment` | String | NOT NULL, **FOREIGN KEY → experiment.name** | 所属实验名称 |
| `benchmark` | String | NOT NULL | benchmark 名称（如 `sqlite3_ossfuzz`） |
| `time_started` | DateTime | 可为 NULL | 试验开始时间 |
| `time_ended` | DateTime | 可为 NULL | 试验结束时间 |
| `preemptible` | Boolean | NOT NULL, 默认 False | 是否使用可抢占实例 |
| `preempted` | Boolean | NOT NULL, 默认 False | 是否已被抢占 |
| `trial_group_num` | Integer | 可为 NULL | 试验组号（同一 fuzzer+benchmark 的第几次重复） |

**作用**：记录每一次独立的模糊测试运行。一个实验通常包含多个 trial（每个 fuzzer × benchmark × 重复次数 = 一个 trial）。

**关系**：
- 一个 `experiment` 有多个 `trial`（一对多）
- 一个 `trial` 有多个 `snapshot`（一对多）

---

### 3. `snapshot` 表 — 快照（定时采集的覆盖率数据）

按固定时间间隔（由 `SNAPSHOT_PERIOD` 配置，通常为 15 分钟）采集的覆盖率度量数据。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `time` | Integer | **PRIMARY KEY**（联合） | 快照时间，单位为秒（从试验开始计算的累计时间） |
| `trial_id` | Integer | **PRIMARY KEY**（联合）, **FOREIGN KEY → trial.id** | 所属试验 ID |
| `edges_covered` | Integer | NOT NULL | 当前覆盖的边数（branch coverage 或 region coverage） |
| `fuzzer_stats` | JSON | 可为 NULL | fuzzer 自定义统计数据（JSON 格式） |

**主键**：`(time, trial_id)` 联合主键

**作用**：记录每个 trial 在各个时间点的覆盖率数据，是最核心的度量数据。用于生成覆盖率随时间变化的曲线图。

**`time` 字段说明**：
- 值为 `cycle * snapshot_period`，例如 snapshot_period=900s（15分钟）时，time 的值为 0, 900, 1800, 2700, ...
- cycle 从 0 开始

**`edges_covered` 字段说明**：
- 尽管列名为 `edges_covered`，实际存储的是 branch coverage（分支覆盖数）或 region coverage（区域覆盖数），取决于实验配置
- 代码中通过 `llvm-cov` 工具的 JSON 输出获取

**`fuzzer_stats` 字段说明**：
- JSON 格式，包含 fuzzer 特定的统计信息
- 内容由各 fuzzer 自定义，可能包含执行速度、语料库大小等信息

**关系**：
- 一个 `trial` 有多个 `snapshot`（一对多）
- 一个 `snapshot` 可以有多个 `crash`（一对多）

---

### 4. `crash` 表 — 崩溃信息

记录在模糊测试过程中发现的崩溃（仅用于 bug benchmark）。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `time` | Integer | **PRIMARY KEY**（联合）, **FOREIGN KEY → snapshot.time** | 发现崩溃的快照时间 |
| `trial_id` | Integer | **PRIMARY KEY**（联合）, **FOREIGN KEY → snapshot.trial_id** | 所属试验 ID |
| `crash_key` | String | **PRIMARY KEY**（联合）, NOT NULL | 崩溃唯一标识符（签名） |
| `crash_type` | String | NOT NULL | 崩溃类型（如 `heap-buffer-overflow`） |
| `crash_address` | String | NOT NULL | 崩溃地址 |
| `crash_state` | String | NOT NULL | 崩溃状态（调用栈摘要） |
| `crash_stacktrace` | String | NOT NULL | 完整的崩溃调用栈 |
| `crash_testcase` | String | NOT NULL | 触发崩溃的测试用例路径 |

**主键**：`(time, trial_id, crash_key)` 联合主键
**外键**：`(time, trial_id)` → `(snapshot.time, snapshot.trial_id)` 联合外键

**作用**：记录每个 snapshot 时间点发现的新崩溃，包含崩溃的详细信息（类型、堆栈、测试用例等）。仅在 bug 类型的 benchmark 中使用。

---

## 表关系图

```
experiment (1) ──→ (N) trial (1) ──→ (N) snapshot (1) ──→ (N) crash
    │                     │                   │                  │
    │  name ◄─FK──  experiment          trial_id ◄─FK──    trial_id
    │                                     time ◄─FK──        time
```

## 数据写入流程

1. **实验初始化** (`dispatcher.py`):
   - 创建 `experiment` 记录
   - 为每个 `fuzzer × benchmark × num_trials` 组合创建 `trial` 记录

2. **试验运行** (`scheduler.py`):
   - 更新 `trial.time_started`（试验开始时）
   - 更新 `trial.time_ended`（试验结束时）

3. **覆盖率测量** (`measure_manager.py`):
   - 每个 snapshot 周期，对每个 trial 测量覆盖率
   - 创建 `snapshot` 记录（`edges_covered` + `fuzzer_stats`）
   - 如果是 bug benchmark，同时创建关联的 `crash` 记录

4. **实验结束** (`dispatcher.py`):
   - 更新 `experiment.time_ended`

## 数据查询示例

主要的查询逻辑在 `analysis/queries.py` 中，典型查询为：

```python
# 获取实验数据（用于生成报告）
session.query(
    Experiment.git_hash, Experiment.experiment_filestore,
    Trial.experiment, Trial.fuzzer, Trial.benchmark,
    Trial.time_started, Trial.time_ended,
    Snapshot.trial_id, Snapshot.time, Snapshot.edges_covered,
    Snapshot.fuzzer_stats, Crash.crash_key
).select_from(Experiment)
 .join(Trial)
 .join(Snapshot)
 .join(Crash, isouter=True)  # LEFT JOIN crash
 .filter(Experiment.name.in_(experiment_names))
 .filter(Trial.preempted.is_(False))
```

## Schema 演进历史（Alembic Migrations）

| 版本 | 日期 | 说明 |
|------|------|------|
| `5c5f07c6f2fa` | 2019-11-18 | 初始版本：创建 experiment、trial、snapshot 三张表 |
| `a7089f396110` | 2019-11-27 | trial 表：`time_created` 改为 `time_started` + `time_ended` |
| `43dc3aacd80e` | 2020-03-27 | experiment 表：增加 `git_hash` 列 |
| `72f7db0e7dfe` | 2020-05-21 | trial 表：增加 `preemptible`、`preempted` 列 |
| `541d041d662a` | 2020-07-09 | experiment 表：增加 `private` 列 |
| `77022369cea4` | 2020-08-10 | experiment 表：增加 `time_ended` 列 |
| `c83ac04855b4` | 2020-08-11 | experiment 表：增加 `experiment_filestore` 列 |
| `26dcc0e12872` | 2020-10-13 | experiment 表：增加 `description` 列 |
| `eec6e5667b87` | 2020-10-16 | snapshot 表：增加 `fuzzer_stats` 列（JSON） |
| `8c237d2acbc4` | 2020-12-01 | 新建 crash 表 |

## 相关源码文件

| 文件 | 说明 |
|------|------|
| `database/models.py` | SQLAlchemy 模型定义（表结构） |
| `database/utils.py` | 数据库连接、会话管理 |
| `database/alembic/versions/` | 数据库迁移脚本 |
| `experiment/dispatcher.py` | 初始化实验和 trial 记录 |
| `experiment/scheduler.py` | 管理 trial 生命周期 |
| `experiment/measurer/measure_manager.py` | 测量覆盖率并写入 snapshot/crash |
| `analysis/queries.py` | 数据查询（用于报告生成） |
