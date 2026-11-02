# 数据契约 v3

所有 JSON 带 `schema_version: 3`。CLI 输出 UTF-8；错误为 `{"schema_version":3,"error":{"type","message"}}`（CLI 退出码 1）或 `{"error":{"status","message"}}`（HTTP 400/403/404/503）。`null` 不能当 0，`unknown` 不能当通过。

## 摘要：status / scan / GET /api/runs

顶层：`version`（工具版本）、`generated_epoch`、`collector`、`last_event_id`（全库最大证据 ID）、`token`、`runs[]`。

- `collector`：`alive`、`heartbeat_age_s`、`pid`、`version`、`interval_s`、`port`、`started_epoch`、`last_error`。`alive` 指有 `run`/`watch` 进程在 3 个间隔（至少 10 秒）内写过心跳；一次性 `scan` 不算在线采集器。
- `token`：只在状态层面变化时改变（各运行的状态、代次、是否结束、关注标志、规则命中，以及采集器是否在线）。新问题记录用 `last_event_id` 追踪；观测时间变化不会改变 token。

每个运行：

- `state`：`status`、`ended`（状态为 complete/failed/incomplete 或日志已出现原生结尾）、`analysis`、`last_logged_time_s`（日志最近给出的仿真时间）、`stop_time_s`（日志给出的瞬态结束时间）、`progress_at_least`（两者之比，是下限）、`observed_epoch`（采集检查时刻）、`source_mtime_epoch`（源日志修改时间）、`quiet_for_s`、`quiet_after_s`、`backlog`、`index_complete`、`error`、`collector_error`、`collector_error_epoch`。
- `attention`：事实型关注原因列表，取值 `failed`、`rule_hit`、`log_quiet`（未结束且日志超过阈值未修改）、`collector_error`、`source_error`。
- `problems`：`printed_count`、`group_count`、`by_severity`、`last_problem_id`、`top`（最多 5 组：级别 → 命中规则 → 参考运行中没有 → 分析中先于读入 → 日志顺序）、`more_groups`。
- `rule_hits[]`：`rule`、`problem_key`、`severity`、`printed_count`、`first_evidence_id`、`first_sim_time_s`、`first_fraction`。
- `baseline`：`run_id`、`status`、`keys_not_in_baseline[]`（`problem_key`、`severity`），未配置为 `null`。
- `measurements`：`records`、`latest`。
- `coverage`：`suppression_seen`、`suppressed_totals`（如 `{"warning": 21700496}`、`{"notice": 195}`，原生全局汇总）、`limitations`。
- `last_event_id`、`token`、`qualification: "not_inferred"`。

## 问题组：problems / GET /api/problems?run=ID

按 `problem_key` 与原生 `severity` 分组，只计已打印的主消息。`problem_key` 为原生编号；无编号消息为“级别:正文（数字掩码为 #）”；工具自身记录为 `premature_termination`、`line_size_limit`；测试台为 `TB:reported_valid=0`、`TB:unparsed_record`、`TB:reported_FAIL`。

每组：`printed_count`、`first_evidence_id`、`last_evidence_id`、`first_observed_epoch`/`last_observed_epoch`（首次/最近一次被采集的墙钟时间）、`code`、`category`（五类之一）、`phase`（分析名，读入阶段为 `setup`）、`first_sim_time_s`（首条消息头行给出的仿真时间，没有为 `null`）、`analysis_stop_s`、`first_fraction`、`suppressed_after`（该键之后出现过逐码抑制）、`severity_source`（`tag` 来自 `WARNING (...)` 标签，`header` 来自头行）、`summary`、`message`。排序：级别，然后首次出现顺序。参数：`generation`（默认当前代）、`after`（只统计该证据 ID 之后的记录）、`limit`（默认 50，上限 500）。

## 测量：measurements / GET /api/measurements?run=ID

测试台记录（含异常记录），按日志顺序返回 `record_type`、`frame`、`code_value`、`reported_valid`、`parse_issue`（若有）、`evidence_id`、`kind`、`observed_epoch`。`tail=N` 返回最新 N 条；`before=ID` 返回该 ID 之前的 `limit` 条；`after=ID` 向后翻。上限 500。

## 原文：evidence ID / GET /api/evidence?id=ID

`source_path`、`line`、`byte_offset`、`observed_epoch`、`header`（头行 `line`/`raw`，没有为 `null`）、`raw`、`continuation`（最多 20 行）、`continuation_limited`、`suppression`（紧随其后的逐码抑制行）、`observed`（`severity`、`severity_source`、`code`、`problem_key`、`instance`、`terminal`、`measured`、`limit`、`analysis`、`sim_time_s`、`analysis_stop_s`、`limitation` 中存在的项）。原文是入库时保存的那一份，不会因源日志轮换读到另一代。

## 详情：details --run ID / GET /api/run-details?run=ID

`source_path`、`indexed_bytes`、`source_bytes`、`source_mtime_epoch`、`version`、`footer`、`analyses`（分析名 → `stop_time_s`）、`suppressed_totals`、`settings[]`（`name`、`requested`、`requested_default`、`effective[]`（`analysis`、`value`、`default`）、`differs`）、`integrity`、`watch`、`baseline`、`quiet_after_s`。

## 等待：wait

`wait [--after ID] [--since TOKEN] [--run ID]... [--timeout S] [--interval S] [--notices] [--repeats]`

返回 `changed`、`changes[]`、`last_event_id`、`token`、`collector`、`runs[]`（受影响运行的摘要）。变化类型：`new_problem_group`（默认不含 NOTICE）、`more_occurrences`（需 `--repeats`）、`status`、`generation`、`rule_hit`、`log_quiet`、`collector_error`、`source_error`、`run_added`、`collector_offline`、`state_changed_since_token`（调用间隙内状态层面已变化）。退出码：0 有变化，3 超时，4 没有在线采集器。

## 健康：GET /api/health

`status`（`ok`/`degraded`）、`mode: read_only`、`version`、`pid`、`started_epoch`、`database`、`collector`。数据库不可用或 schema 不符时 `status=degraded` 并给出 `database_error`。

## 存储

一个 SQLite 库（`PRAGMA user_version = 3`）：`runs`（配置、游标与解析上下文、采集摘要）、`events`（每条证据一行，列 `observed`、`stream`、`problem_key`、`sim_time` 带索引，原始负载在 `payload`）、`collectors`（心跳）。`stream`：`problem`、`measurement`、`continuation`、`suppression`、`state`，仅作内部索引。旧 schema 的库会被拒绝且不被修改。

## 原始事件（调试/导出）

`events` 命令返回入库负载：`event_id`、`observed_epoch`、`run_id`、`generation`、`category`、`kind`、`severity`、`code`、`problem_key`、`analysis`、`sim_time_s`、`source_path`、`line`、`byte_offset`、`raw`，以及消息、设置、抑制、测试台记录各自的字段。日常取证应使用上面的按需接口。
