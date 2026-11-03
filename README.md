# Spectre Log Inspector · v0.4

在长时间 Spectre 仿真还在跑的时候，尽早把问题交给执行 Agent 和人：Agent 读紧凑的文本或 JSON，人看一个只留关键信息的本地页面。工具只读：不启动、不停止、不修改仿真，不推断电路原因，不判断码字，不做杂散分析。停不停由人或 Agent 决定。

**Python 3.10+，零第三方依赖。** 已用 Spectre 21.1.0.509.isr12 的真实日志验证；Windows、Python 3.13。

**仓库链接是默认交付入口。** 陌生机器上的 Agent 先读 [AGENTS.md](AGENTS.md) 和 [从仓库开始](docs/agent-quickstart.md)，克隆后即可用源码运行；pip 安装为可选项。远端访问见 [SSH 配置与部署](docs/ssh.md)。当前提供 CLI/JSON 和只读 HTTP，没有 MCP 服务，也未发布到公共包索引。

GitHub 仓库：[chenzc24/spectre-log-inspector](https://github.com/chenzc24/spectre-log-inspector)。私有仓库需要接收方先获得 GitHub 读取权限。可直接转交的提示见 [Agent 上手提示](docs/agent-prompt.md)。

离线环境也可用 `python scripts/package_handoff.py` 生成 ZIP（wheel、合成样例和说明），见 [离线安装](docs/handoff.md)。

## 从仓库开始

Windows 使用 `python` 或 `py -3`，Linux/macOS 通常使用 `python3`；需要 Python 3.10+。若使用镜像仓库，替换下面的 URL。

```sh
git clone https://github.com/chenzc24/spectre-log-inspector.git spectre-log-inspector
cd spectre-log-inspector
python -m simcheck --version
python -m simcheck --db .runtime/onboarding.sqlite scan examples/real-fixtures.json --json
```

这条路径不需要 pip、第三方包、Spectre 安装或许可证。示例扫描后退出，不启动仿真。要查看真实运行，还需提供本机可读的日志清单；远端则需提供已授权的 SSH 主机别名和服务器上的日志/工作目录。URL 本身不包含这些私有配置。Agent 的输出和等待循环见 [使用契约](docs/agent-handoff.md)。

## 快速开始

```powershell
python -m simcheck --db .runtime/demo.sqlite run examples/real-fixtures.json --open
```

一个前台进程同时采集和提供页面（默认 <http://127.0.0.1:8765>），Ctrl-C 停止。端口被占用时在采集前报错；`--port 0` 自动选端口。也可双击 `Start-Viewer.cmd`。

想先看小样例：用 `examples/synthetic-cases.json` 替换上面的清单，并使用新库 `.runtime/synthetic-demo.sqlite`。这份清单有 6 个手写合成案例，覆盖正常结束、运行中告警、FATAL 与 exit 0 冲突、缺少结尾、raw 不完整和分析名不匹配；详见 [样例与提取结果](docs/examples.md)。

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
- 进度取日志最近给出的仿真时间（`t>=…`，是下限）。Spectre 自己的进度条更靠前时，再加一个 `meter N%`（误差 ±1 格，约 1.4%）。日志长时间没有时间行时、DC/AC 扫描时，都靠这个读数看进度。`frames N` 只数能解析出的 R4MEAS 帧，其他测试台行写成 `(+N other TB lines)`。
- `wait` 只返回变化，每条一行：新问题组、状态变化、规则命中、日志超时未更新、采集出错、采集器离线；末行是下一次调用。退出码 0 有变化，3 超时，4 没有在线采集器。已知问题再次出现、新的 NOTICE 组默认不唤醒（`--repeats`、`--notices`）。
- `show` 默认列错误、警告、测试台问题和命中规则的提示，其余提示只给数量（`--all` 全列）；消息最长 160 字，全文用 `evidence`。
- 时间写法与 Spectre 日志一致（ns、us），可以直接对照原文；`x5 then suppressed` 表示打印 5 次后被抑制，实际次数未知。

HTTP 给出同样的 JSON（只读，只绑定 127.0.0.1，只接受本机 Host 头）：`/api/status`、`/api/show?run=`、`/api/evidence?id=`、`/api/measurements?run=`、`/api/details?run=`、`/api/health`。完整字段见 [数据契约](docs/schema.md)。

## 页面

页面使用英文界面和固定浅色主题，主体为白色。采集状态只显示一处；Failed、Unknown、Incomplete evidence 保持明显。左侧运行列表按需要关注排序：失败和命中规则是红色竖条，日志超时、采集出错是琥珀色，正常结束的不着色；窄屏改为运行下拉选择器。右侧把仿真进度集中在时间轴附近；Spectre 进度条读数靠前时显示 `Meter N%`。问题保持原来的紧凑横排：级别、编号、次数、首次时间/百分比、tag、正文。正文深色，次数和时间用灰色小字，Rule/参考标记保留红色/琥珀色描边。展开后只显示 First/Last、灰色来源路径和原文；完整规则名和参考运行可通过 tag 提示查看，窄屏自动换行。标签页为 Problems、Measurements（最新 50 条，View 展开原文）、Details（完整性检查和设置对照）。开启 Notifications 后，新问题、失败、规则命中、日志超时、采集器离线会发浏览器通知。Pause updates 只暂停页面自动刷新。

左侧每条记录的 `×` 可从当前浏览器列表关闭，刷新后保持；`Restore closed` 恢复。
关闭保留采集和证据，新代次会重新出现。`↓` 提供 HTML report 和 JSON data 下载：
保存当前代次的采集快照、问题、检查与所有已入库原始事件，供离线查看或 Agent 读取。
快照不包含源日志和波形文件本身。窄屏在运行选择器旁提供相同操作。

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

共享盘采用一层运行目录时，可以用 `roots` 代替或补充 `runs`。下面的配置将 `/shared/jobs/A` 登记为 `farm/A`，即使它还没有日志。只有明确配置的 state 才能证明作业正在排队。更深或不规则的目录继续用显式 `runs`。

```json
{"roots":[{"root":"/shared/jobs","alias":"farm","log":"logs/spectre.out","state":"state.json","exclude":["scratch","archive-*"]}]}
```

`scan` 发现一次，`run` 和 `watch` 每 30 秒检查根目录，属性不变时复用目录列表，每 5 分钟重新列举。每个运行独立调度，活跃运行按 `--interval` 检查，安静或已结束的运行逐步退避到 60 秒。移出发现范围会停止追踪并保留证据。将 SQLite 库放在监测机器的本地磁盘。

## 证据边界

- 时间只取消息所在块的头行（`Warning from spectre at time = …`）；头行没有时间就是没有时间。
- Spectre notice 没有编号，级别取头行，按正文（数字掩码）归组，保留 NOTICE 级别。`N warnings/notices suppressed` 是原生全局汇总，不分摊到编号。
- 完成不等于电气或码字合格；exit 0 加 FATAL、资源限额不算通过；无结尾行且无可信状态时为 unknown。R4MEAS 的 `reported_valid` 只是测试台原值。
- 带编号的标签（`ERROR (SFE-23):`）是原生消息；不带编号的 `ERROR:`、`FATAL:` 只有缩进在 Spectre 头行块内才算原生。块外行首的这类行（例如测试台打印的）保留原文，归为 `TB:reported_ERROR` 等，不计为 Spectre 错误。
- 问题组的阶段取所在分析：瞬态、DC、AC、Monte Carlo 的分析横幅，或头行里的 `during … analysis` 子句。DC/AC 头行给出的是扫描点（`at vcm = …`），不是时间。
- 只对已测格式承诺；不解析没有 Spectre 头行的自然语言文本。

## 运行和项目管理

- `run` 一个进程采集加页面；也可以 `watch 清单` 单独采集、`serve` 单独提供页面。采集器每轮写心跳；一个运行出错不会挡住其他运行。
- 数据库是源日志的派生索引（SQLite WAL，单写者，schema 4）。升级时指定新的本地 `--db` 路径并重新采集。旧库只可用对应版本查询。Agent 在新库上先调用 `status` 获取新的等待游标。
- 源文件被替换、截断或出现新的 Spectre 启动段时开新代次，旧代次证据保留。查看旧代次证据时会注明代次；如果文件已被替换，path:line 指向的是旧内容，raw 仍是入库时的原文。
- `.runtime/`、原始私有日志和数据库被 Git 忽略。无后台自启动、计划任务、自动清理、自动 commit/push。日志含实例和路径，只在本机访问。

## 测试与文档

```powershell
python -m unittest discover -s tests -v
python scripts/benchmark.py
```

8 组脱敏真实日志和 6 份真实 logStatus 在 `tests/fixtures`，hash 在 `provenance.json`。详见 [设计](docs/design.md)、[数据契约](docs/schema.md)、[验证记录](docs/validation.md)、[实施记录](plan/log.md)。

2026-11-03新增14组实际Spectre故障注入/ADC短仿语料与必要回归，见[原生仿真验证](docs/live-spectre-validation.md)。其中两项追加覆盖仍排队，未当作通过。随后据原生日志做了五项修正：进度条、帧数、块外未编号标签、旧代次证据、DC/AC 阶段，见[验证记录](docs/validation.md)。
