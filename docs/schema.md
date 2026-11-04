# 数据契约（API 4）

CLI 默认输出文本；`--json` 和 HTTP 输出同样内容的 JSON，都带 `v: 4`。

- 缺省的键表示 false、无或 0：不输出 null、false 和空集合（`collector.live` 总是给出）。
- 时间单位是秒，保留 6 位有效数字；`pct` 是百分比，不是比例。
- 证据句柄 `e` 是全库递增的整数，文本里写作 `eNNN`；CLI 和 HTTP 都接受 `eNNN` 或纯数字。
- 每个输出都有上限，保证不会塞满 Agent 的上下文（见各节）。

## status（GET /api/status，`?run=` 只看一个）

顶层：`v`、`version`、`cursor`、`collector`（`live`、`hb` 距上次心跳秒数、`pid`、`version`、`error`）、`runs`。`runs` 的顺序：失败或命中规则，其他关注原因，无关注；同一级里未结束的在前。

| 键 | 含义 |
|---|---|
| `run` | 运行 ID |
| `state` | complete、failed、incomplete、unknown、running、indexing 等 |
| `ended` | 已结束：终态，或日志已有原生结尾行 |
| `flags` | 关注原因：failed、rule、quiet（未结束且日志超过阈值未修改）、collector_error、source_error |
| `analysis`、`stop` | 当前分析名（瞬态、DC、AC、Monte Carlo；取最近的分析横幅或头行的 `during` 子句），日志给出的瞬态结束时间 |
| `t`、`pct` | 日志最近给出的仿真时间及其占结束时间的百分比（下限）；正常结束的运行不给 |
| `meter` | Spectre 70 格进度条的读数，单位为百分比，误差在 ±1 格（约 1.4%）以内，不能当作下限；比 `pct` 靠前或没有时间时才给出；正常结束的运行不给。DC/AC 分析没有 `stop` 和 `t`，进度只来自这里 |
| `n` | 问题组数：`E` 错误/致命，`W` 警告，`T` 测试台，`N` 提示 |
| `errors` | 最多 2 个错误/致命组，按日志顺序（组摘要） |
| `rules` | 每条规则一项：`rule`、`keys`（前 5 个）、`n`（总组数，多于 5 时）、最早一次的 `e`、`t`、`pct` |
| `base` | 参考运行中没有的非 NOTICE 键：`ref`、`new`（前 5 个）、`n`（总数，多于 5 时） |
| `frames` | 解析出的 R4MEAS 帧数 `n`；其他测试台行数 `other`（无法解析的记录、原始 PASS/FAIL、块外未编号标签行）；最新一个解析帧的 `frame`、`code` |
| `log_age` | 未结束的运行：日志距上次修改的秒数 |
| `error` | 采集或读日志的错误 |
| `gen` | 代次，大于 1 时给出 |
| `last_problem` | 最新问题记录的证据 ID，页面据此决定是否重新取问题组 |

组摘要：`e`（首条证据）、`sev`（原生级别，测试台为 INFO）、`key`（原生编号；无编号消息为“级别:数字掩码后的正文”；工具记录为 premature_termination、line_size_limit；测试台为 TB:…，其中 Spectre 头行块外未编号的 `ERROR:` 等行为 `TB:reported_ERROR` 等，级别为 INFO，不计为 Spectre 错误）、`n`（已打印次数）、`sup`（之后被逐码抑制）、`t`、`pct`（首条消息头行给出的仿真时间）、`msg`（摘要，status 里最长 120 字，show 里 160 字）。

`cursor` 形如 `3795.654c760c1427`：已交付的证据位置加状态摘要；状态分页期间还能包含续页信息。游标应视为不透明值，原样传给下一次 `wait`。

## show（GET /api/show?run=ID&full=1）

运行头（`state`、`flags`、`analysis`、`stop`、`t`、`pct`、`log_age`、`log` 日志路径、`baseline`）加 `groups`。每组是组摘要加：`last`（末条证据，多于一条时）、`phase`（分析名，读入阶段为 setup）、`rules`（命中的规则名）、`base_new`（参考运行中没有）。

排序：错误、警告、测试台、提示；同一级里分析阶段先于读入阶段，再按日志顺序。默认不列未命中规则的 NOTICE 组（`hidden_notices` 给数量），最多 30 组（`more` 给待处理数的下界）；`--all` 或 `full=1` 包含 NOTICE，每页最多 500 组。所有组均参与规则判定和计数。有剩余组时，用返回的 `next_offset` 作为 `--offset` 或 HTTP `offset` 读取下一页；若多页的 `revision` 不同，应从第一页重新读取。

## evidence（GET /api/evidence?id=eNNN）

`e`、`run`、`gen`（代次，大于 1 或不是当前代次时给出）、`latest_gen`（证据来自旧代次时给出当前代次）、`replaced`（此后源文件被替换：`path`:`line` 指向的是旧内容；同一文件中追加的先前尝试没有这个键，行号仍有效）、`path`、`line`、`off`（字节偏移）、`sev`、`key`、`t`、`pct`、测试台字段（`frame`、`code`、`valid`、`issue`）、`limitation`、`group`（`n`、`sup`、`first`、`last`）、`seen`（首次被采集的时刻）、`header`（头行 `line`、`raw`）、`raw`、`cont`（续行，最多 20 行；`cont_more` 表示还有）、`suppression`（紧随其后的逐码抑制行）。原文是入库时保存的那一份，不会因源日志轮换变成另一代。

## wait

`wait [--cursor C] [--run ID]... [--timeout 3600] [--interval 2] [--notices] [--repeats]`

返回 `changed`、`changes`（最多 20 条，`more` 给待处理数的下界）、`cursor`；没有变化时 `reason` 为 timeout 或 collector_offline。变化类型：

- `new`：新问题组（组摘要；命中规则时带 `rules`）
- `rule`：已有组新命中规则（`rule`、`key`、`e`、`t`、`pct`）
- `status`（`from`、`to`），`restart`（`gen`），`quiet`（`log_age`），`collector_error`、`source_error`（`error`），`run_added`，`collector_offline`（`hb`）
- `more`：已知组又出现（仅 `--repeats`）
- `state_changed`：cursor 之后状态层面有变化，细节看 status。状态变更超过一页时以 `state_snapshot` 分页核对当前状态。
- `more` 非零时，使用返回游标和相同过滤条件继续调用 wait。采集器离线时先返回尚未读取的已入库告警，读完后返回退出码 4。

退出码：0 有变化，3 超时，4 没有在线采集器。

## measurements（GET /api/measurements?run=ID）

`total`、`rows`（`e`、`frame`、`code`、`valid`，或 `issue`、`raw`）、`older`、`newer`（继续翻页还有记录）。默认最新 20 条；`--tail N`、`--before eNNN`、`--after eNNN`，每页最多 500 条。

## details（GET /api/details?run=ID）

`status`、`log`、`indexed`、`size`（字节）、`spectre`（版本）、`stops`（有结束时间的瞬态分析：分析名到结束时间）、`footer`（errors、warnings、notices）、`suppressed`（原生汇总，不能分摊到编号）、`coverage`、`pending_line`、`checks`（state、log_status、raw 的观察结果）、`settings`（`name`、`req`、`eff`、`def`、`diff`）。

## 另存（GET /api/export?run=ID&format=html|json|txt）

返回带 `Content-Disposition: attachment` 的 UTF-8 文件，默认 JSON。导出在一个
SQLite 只读事务内完成；不重新读取源日志，不修改采集器、数据库或仿真。
HTML 为不依赖服务的静态报告。JSON 为独立导出格式（`export_version: 1`，内含
API `v: 4`），包括：

- `run`、`saved_at`（UTC）、工具 `version`。
- `scope`：`generation`、`events` 总数、`problem_groups` 总数、`source_files_embedded: false`。
- `summary`、`problems`、`details`：相同快照内的状态、问题组与完整性/设置。
- `coverage`：抑制汇总和原有证据限制。
- `events`：当前代次全部已入库事件的原始负载，加 `event_id`、`observed_epoch`；不受测量分页的 500 条上限影响。
- `export_complete: true`：文件成功导出，与运行是否成功无关；unknown/incomplete/failed 原样保留。

问题摘要保留原有最多 500 组和文本长度限制；`scope.problem_groups` 给出实际总组数，
所有原始事件仍在 `events` 中，HTML 的 Stored evidence 部分同样全列。源文件未入库的
行和波形文件不嵌入快照。先分块序列化到临时文件（超过 1 MiB 转磁盘），成功后带
Content-Length 下载；源日志轮换或离线不会改变已保存原文。

## health（GET /api/health）

`status`（ok 或 degraded）、`version`、`pid`、`started`、`db`、`collector`；数据库不可用时给 `error`。

## 错误

CLI 文本为 `error: 类型: 信息`，`--json` 为 `{"v":4,"error":{"type":…,"message":…}}`，退出码 1；格式不对的句柄由参数解析拒绝，退出码 2。HTTP 为 `{"v":4,"error":{"status":…,"message":…}}`，状态码 400、403、404、503。

## 存储

SQLite 的 `PRAGMA user_version` 为 4。一次写事务提交事件、运行游标、问题组计数与首末证据 ID、抑制标记、来源路径和变更序号。路径按运行和代次保存，导出时还原为原始事件契约。查询当前问题组读取 `groups`。等待无变化时检查变更序号、心跳和静默期限。带 `--repeats` 的历史游标需要统计游标之后的新增事件。升级请用新库重采，证据句柄和等待游标仅在原库有效。

## 原始事件（调试/导出）

`events` 命令输出入库负载（JSON），日常取证用上面的接口。
