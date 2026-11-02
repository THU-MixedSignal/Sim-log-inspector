# Spectre Log Inspector · v0.3

在长时间 Spectre 仿真**还在跑的时候**尽早把问题摆到人和 Agent 面前，避免把几小时到几天的时间花在注定无效的仿真上。工具只读：抓取原生告警、提示、设置、进度、测试台记录和结束状态，按仿真时间标出每类问题首次出现的位置并发出提醒；不推断电路原因，不判断码字是否正确，不做杂散分析，也**不会停止仿真**——停不停由人决定。

**Python 3.10+，运行时零第三方依赖。** 已验证真实日志版本 Spectre 21.1.0.509.isr12；Windows Python 3.13 测试。其他版本尚未正式支持。

## 快速开始

在仓库根目录运行（不必安装）：

```powershell
python -m simcheck --db .runtime/demo.sqlite run examples/real-fixtures.json --open
```

一个前台进程同时采集和提供网页（默认 <http://127.0.0.1:8765>），Ctrl-C 停止。端口被占用时会在采集前直接报错并说明原因；用 `--port 0` 自动选空闲端口。也可双击 `Start-Viewer.cmd`，自动选端口并打开浏览器。

## 页面上看什么

- **左侧运行列表按“需要关注”排序**：失败、命中关注规则、日志长时间未更新、采集出错的运行在前；仍在运行的排在已结束的前面，因为停掉它们才省时间。颜色只表示“请看这里”，已正常结束的运行不着色，避免被读成“合格”。
- **仿真时间轴**：横轴是瞬态分析 0 → 结束时间（取自日志 `Transient Analysis … (0 s -> stop)`），进度条是日志已记录到的时间（下限）。每组警告、错误、测试台问题（以及命中规则的提示）在其**首次出现的仿真时间**处标记；挤在一起的标记合并为一个，直接标出“N 组，最早 60.096 ns（0.058%）”。
- **问题列表**按阶段分组（分析中 / 测试台报告 / 读入与初始化），每组给出原生级别、编号、已打印次数、首次仿真时间及占比、首次采集时间，并标注“新出现”“之后被抑制，实际次数未知”“规则：…”“参考运行中没有”。提示（NOTICE）保留原生级别，默认折叠，不升级为告警。
- **点开即看原文**：头行（给出时间的那一行）、消息行、续行和逐码抑制行，带源行号和字节偏移。
- **测量**默认显示最新 50 条，可向前加载；**设置**把用户请求值和分析实际生效值并排，标出不同；**完整性**是逐项检查清单。
- **提醒**：点“开启提醒”后，新问题组、状态变为失败、新的规则命中、日志超过阈值未更新、采集器停止心跳时发浏览器通知；标签页标题显示需要关注的运行数。“标为已读”只记在本浏览器。
- 采集进程每轮写心跳；页面在采集器离线或版本与查看器不一致时给出横幅，不会让停住的数据看起来仍在更新。

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

- 只有 `id`/`log` 必需。`watch` 可写在顶层（所有运行共用）或单个运行里；规则字段 `code`（通配）、`key`（问题组键，通配）、`severity`、`text`（子串）、`min_count` 同时满足才算命中。**规则是你们的判据**，工具只报告“命中”这个事实，不自行判断哪些告警意味着仿真作废。
- `baseline` 指定同一测试台的参考运行，列出参考运行里从未出现过的编号（事实对比，不推断原因）。
- `quiet_after_s`：运行未结束而日志超过这么久没有修改时提醒（默认 1800 秒）。这是“日志多久没更新”的事实，不是“卡死”的结论；等待许可证等情况也会触发。
- `raw` 只支持 PSF ASCII 头尾快速检查，不扫描整个波形；独立 logStatus 检查要指定目标 `analysis`。`state` 只读现有 managed 单阶段状态 JSON。清单必须指向不可混用的运行目录，v1 不自动证明 sidecar 与日志属于同一次远端运行。
- 远端仿真：把本仓库部署到服务器上采集并用 SSH 端口转发查看，或把日志只读挂载/同步到本机。工具不内置 SSH、凭据或作业控制。

## Agent 接口

所有命令向 stdout 输出 **UTF-8 JSON**（与控制台代码页无关）；出错时同样输出 JSON（`{"error": {...}}`）并以 1 退出。读命令只读打开数据库，不会创建或升级它。

```powershell
python -m simcheck scan examples/real-fixtures.json        # 采集到追平后输出摘要
python -m simcheck status                                  # 当前摘要（含 token、last_event_id、collector）
python -m simcheck wait --after <last_event_id> --since <token> --timeout 3600
python -m simcheck problems --run noise
python -m simcheck measurements --run noise --tail 20      # 最新 20 条；--before <id> 向前翻
python -m simcheck evidence 123                            # 原文、头行、续行、抑制行
python -m simcheck details --run noise                     # 设置对照、完整性、规则
python -m simcheck report                                  # Markdown 报告
```

`wait` 是给 Agent 的早发现原语：阻塞到出现新问题组、状态变化、新规则命中、日志超时未更新、采集出错或采集器离线，然后返回带 `changes` 的 JSON；退出码 0 有变化、3 超时、4 没有在线采集器。把上次结果里的 `last_event_id`/`token` 传给下一次，两次调用之间的变化不会丢。默认不因已知问题重复出现或新的 NOTICE 组唤醒（`--repeats`、`--notices` 可打开）。适合放进后台任务：仿真没出事时不需要模型反复查看。

HTTP GET（只绑定 127.0.0.1，只接受本机 Host 头）：`/api/runs`、`/api/problems?run=`、`/api/measurements?run=&tail=`、`/api/evidence?id=`、`/api/run-details?run=`、`/api/health`（版本、PID、采集器心跳）。无写端点、无文件浏览、无进程控制。

## 运行和项目管理

- `run` 一个进程采集加网页；也可 `watch 清单` 单独采集、`serve` 单独提供网页。采集器在落后时连续处理（每轮每个运行最多 2 MiB、单行 64 KiB），追平后按间隔轮询；一个运行出错不会挡住其他运行，错误会显示在该运行上。
- 数据库是源日志的派生索引（SQLite WAL，单写者事务，schema 3）。旧版本创建的数据库会被**拒绝且保持不动**：换一个新的 `--db` 路径重新采集即可。
- 增量识别使用文件身份、前缀 hash 和已读边界 anchor；源文件被替换、截断或出现新的 Spectre 启动段时开新代次（generation），旧代次证据保留。相同文件中间的静默原地修改不能完全检测。
- `.runtime/`、原始私有日志和数据库被 Git 忽略。无后台自启动、计划任务、自动清理、自动 commit/push。日志含实例和路径等敏感信息；仅本机访问，脱敏后再分享。

## 证据边界

- 时间只取自该消息所在块的头行（`Warning from spectre at time = …`）；头行没有时间就是“无仿真时间”，不沿用上一条消息的时间。
- Spectre 的 notice 没有编号标签，级别取自头行（`Notice from spectre …`），按正文（数字掩码）归组；`N warnings/notices suppressed` 是原生全局汇总，不分摊到各编号；逐码 “Further occurrences … suppressed” 只说明之后被抑制，实际次数未知。
- 完成 ≠ 电气或码字合格；exit 0 + FATAL、资源限额不能通过；无 footer 且无可信状态时为 unknown。R4MEAS 的 `reported_valid` 只是测试台原值，不是工具的正确码判定。
- 只对当前已测格式承诺；不解析没有 Spectre 头行的自然语言文本，也不声明支持 Xcelium/HSPICE。

## 测试与文档

```powershell
python -m unittest discover -s tests -v
python scripts/benchmark.py
```

8 组脱敏真实日志在 `tests/fixtures`，原始与脱敏 hash 在 `provenance.json`。测试另覆盖逐字节、重启、轮换、多次启动、exit0/FATAL、raw 截断、头行时间、notice、抑制、规则、参考对比、日志超时、采集隔离、`wait`、UTF-8 输出、HTTP Host 校验与 JSON 错误。

详见 [设计](docs/design.md)、[数据契约](docs/schema.md)、[验证记录](docs/validation.md)、[实施记录](plan/log.md)。
