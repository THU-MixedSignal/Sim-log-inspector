# Spectre Log Inspector · v0.4

在长时间 Spectre 仿真还在跑的时候，尽早把问题交给执行 Agent 和人：Agent 读紧凑的文本或 JSON，人看一个只留关键信息的本地页面。工具只读：不启动、不停止、不修改仿真，不推断电路原因，不判断码字，不做杂散分析。停不停由人或 Agent 决定。

**Python 3.10+，零第三方依赖。** 已用 Spectre 21.1.0.509.isr12 的真实日志验证；Windows、Python 3.13。

## 快速开始

```powershell
python -m simcheck --db .runtime/demo.sqlite run examples/real-fixtures.json --open
```

一个前台进程同时采集和提供页面（默认 <http://127.0.0.1:8765>），Ctrl-C 停止。端口被占用时在采集前报错；`--port 0` 自动选端口。也可双击 `Start-Viewer.cmd`。

## 给 Agent

默认输出是紧凑文本，每行一个事实。`eNNN` 是证据句柄，`cursor` 是等待游标，都可以原样传回；`--json` 输出同样内容的 JSON，空字段省略。设置 `SIMCHECK_DB` 后不必每次写 `--db`。

```powershell
python -m simcheck status                      # 所有运行，需要关注的在前；末尾给 cursor
python -m simcheck wait --cursor 3795.654c760c1427   # 阻塞到有需要关注的变化；给出下一条命令
python -m simcheck show minstep                # 一个运行的问题组：编号、次数、首次仿真时间、句柄
python -m simcheck evidence e3705              # 原文行和 path:line
python -m simcheck measurements noise --tail 20
python -m simcheck details noise               # 完整性检查、请求值与生效值
```

`status`（8 组示例日志共 2.4 KB 文本、3.7 KB JSON）节选：

```
no collector running: data is not updating; 8 runs, 7 need attention; cursor 3795.654c760c1427
minstep: failed, rule hit | tran_test t>=1.14929ns/820ns (0.140%) | E2 W2 N6
  e3705 ERROR SPECTRE-16927 x1 @1.14929ns (0.140%): Cannot run the simulation because transient analysis has reached…
  rule 瞬态不收敛（示例规则）: "Newton iteration fails to converge at time = # ps step = # s."; first e3694 @95.0439ps (0.012%)
a_fft: complete | tran_perf | W5 N5 | frames 1032
```

- 每个运行一行：状态和关注原因、仿真进度（未正常结束时）、问题组数（E 错误/致命，W 警告，T 测试台，N 提示）。需要关注的运行下面列出首个错误、规则命中、参考运行中没有的编号，各带句柄和首次出现的仿真时间。
- `wait` 只返回变化，每条一行：新问题组、状态变化、规则命中、日志超时未更新、采集出错、采集器离线；末行是下一次调用。退出码 0 有变化，3 超时，4 没有在线采集器。已知问题再次出现、新的 NOTICE 组默认不唤醒（`--repeats`、`--notices`）。
- `show` 默认列错误、警告、测试台问题和命中规则的提示，其余提示只给数量（`--all` 全列）；消息最长 160 字，全文用 `evidence`。
- 时间写法与 Spectre 日志一致（ns、us），可以直接对照原文；`x5 then suppressed` 表示打印 5 次后被抑制，实际次数未知。

HTTP 给出同样的 JSON（只读，只绑定 127.0.0.1，只接受本机 Host 头）：`/api/status`、`/api/show?run=`、`/api/evidence?id=`、`/api/measurements?run=`、`/api/details?run=`、`/api/health`。完整字段见 [数据契约](docs/schema.md)。

## 页面

左侧运行列表按需要关注排序：失败和命中规则是红色竖条，日志超时、采集出错是琥珀色，正常结束的不着色。右侧只有状态和命中的规则、问题计数、仿真进度、仿真时间轴（标出各组问题首次出现的位置）、问题列表（一组一行，点开看原文）、测量（最新 50 条）、详情（完整性检查和设置对照）。开启“提醒”后，新问题、失败、规则命中、日志超时、采集器离线会发浏览器通知。

## 清单（manifest）

路径相对于清单文件：

```json
{
  "quiet_after_s": 1800,
  "watch": [
    {"name": "SOA 越限", "code": "CMI-275*"},
    {"name": "瞬态不收敛", "text": "Newton iteration fails to converge"},
    {"name": "TB 报告无效", "key": "TB:reported_valid=0", "min_count": 3}
  ],
  "runs": [{
    "id": "my-run",
    "log": "D:/results/my-run/spectre.out",
    "state": "D:/results/my-run/simulation.state.json",
    "log_status": "D:/results/my-run/raw/logStatus",
    "analysis": "tran_perf",
    "raw": "D:/results/my-run/raw/tran_perf.tran.tran",
    "expected_stop_s": 0.000103259,
    "baseline": "reference-run"
  }]
}
```

- 只有 `id`、`log` 必需。`watch` 可写在顶层或单个运行里；`code`（通配）、`key`（问题组键，通配）、`severity`、`text`（子串）、`min_count` 同时满足才算命中。规则是你们的判据，工具只报告命中。
- `baseline` 指定同一测试台的参考运行，列出参考运行里没有出现过的编号。
- `quiet_after_s`：运行未结束而日志超过这么久没有修改时提醒，默认 1800 秒。这是日志多久没更新的事实，不是卡死的结论。
- `raw` 只做 PSF ASCII 头尾检查；logStatus 检查需要指定 `analysis`；`state` 只读现有 managed 状态 JSON。清单要指向不会混用的运行目录。
- 远端仿真：把仓库部署到服务器上采集并用 SSH 端口转发查看，或把日志只读挂载到本机。工具不内置 SSH、凭据或作业控制。

## 证据边界

- 时间只取消息所在块的头行（`Warning from spectre at time = …`）；头行没有时间就是没有时间。
- Spectre notice 没有编号，级别取头行，按正文（数字掩码）归组，保留 NOTICE 级别。`N warnings/notices suppressed` 是原生全局汇总，不分摊到编号。
- 完成不等于电气或码字合格；exit 0 加 FATAL、资源限额不算通过；无结尾行且无可信状态时为 unknown。R4MEAS 的 `reported_valid` 只是测试台原值。
- 只对已测格式承诺；不解析没有 Spectre 头行的自然语言文本。

## 运行和项目管理

- `run` 一个进程采集加页面；也可以 `watch 清单` 单独采集、`serve` 单独提供页面。采集器每轮写心跳；一个运行出错不会挡住其他运行。
- 数据库是源日志的派生索引（SQLite WAL，单写者，schema 3）。旧版本的库会被拒绝且保持不动，换一个新的 `--db` 路径重新采集即可。
- 源文件被替换、截断或出现新的 Spectre 启动段时开新代次，旧代次证据保留。
- `.runtime/`、原始私有日志和数据库被 Git 忽略。无后台自启动、计划任务、自动清理、自动 commit/push。日志含实例和路径，只在本机访问。

## 测试与文档

```powershell
python -m unittest discover -s tests -v
python scripts/benchmark.py
```

8 组脱敏真实日志和 6 份真实 logStatus 在 `tests/fixtures`，hash 在 `provenance.json`。详见 [设计](docs/design.md)、[数据契约](docs/schema.md)、[验证记录](docs/validation.md)、[实施记录](plan/log.md)。
