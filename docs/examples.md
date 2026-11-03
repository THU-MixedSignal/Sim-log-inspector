# 样例与提取结果

## 已有真实语料与新增合成样例

`examples/real-fixtures.json` 使用 8 组脱敏真实日志，来源与 hash 见
`tests/fixtures/provenance.json`。这些日志用于回归，不需要启动仿真。

`examples/synthetic-cases.json` 使用 6 个手写合成案例。所有消息、实例名、数值和
sidecar 均为演示编写，没有执行模拟器，没有使用私有输入。每个输入文件的 SHA-256
见 `tests/fixtures/synthetic/provenance.json`；预期事实固定在
`tests/test_synthetic_examples.py`。它们用于展示接口与证据边界，不增加厂商版本覆盖。

| 运行 | 输入中的关键事实 | 预期状态 |
|---|---|---|
| `demo-complete` | 原生结尾 0 errors；目标分析 PASS；raw 有 END 并保存到 100 ns | `complete` |
| `demo-warning` | running 状态快照；CMI-2753 打印两次后抑制；NOTICE；valid=0 和短记录 | `running`，命中示例规则 |
| `demo-fatal-exit0` | 包装状态为 complete、exit 0，但原生记录为 FATAL | `failed` |
| `demo-no-footer` | 进度已到 100 ns / 100 ns，有自然语言 PASS，没有原生结尾或状态文件 | `unknown` |
| `demo-raw-incomplete` | 原生结尾 0 errors，但 raw 只有 40 ns，缺少 END，预期结束为 100 ns | `incomplete` |
| `demo-analysis-mismatch` | 原生结尾 0 errors，logStatus 是其他分析的 PASS | `incomplete` |

`running` 是冻结样例里的报告状态，没有关联真实仿真进程。这份清单用
`quiet_after_s: 0` 关闭日志过久未更新提醒，避免静态文件随时间变老改变演示结果。
`watch` 是示例关注判据；命中只说明文本符合规则。`complete` 仅表示所配置来源的
完成性检查通过，不证明电气性能或码字合格。raw 只检查 PSF ASCII 头部与最多 64 KiB
尾部，不验证完整波形；这些 raw 文件也是专为检查器编写的合成片段。

## 运行

在仓库根目录执行；数据库请与其他演示分开：

```powershell
python -m simcheck --db .runtime/synthetic-demo.sqlite scan examples/synthetic-cases.json
python -m simcheck --db .runtime/synthetic-demo.sqlite show demo-warning --all
python -m simcheck --db .runtime/synthetic-demo.sqlite measurements demo-warning --tail 20
python -m simcheck --db .runtime/synthetic-demo.sqlite details demo-raw-incomplete
```

把 `show` 返回的 `eNNN` 句柄传给 `evidence`，即可读取原文和 `path:line`。
句柄由当前数据库分配，不应跨库复用。以上命令加 `--json` 可供 Agent 读取。

页面入口（一个前台进程采集这些静态文件并提供页面）：

```powershell
python -m simcheck --db .runtime/synthetic-demo.sqlite run examples/synthetic-cases.json --port 0 --open
```

Ctrl-C 只停止本工具。若仅用 `scan` 后的库启动 `serve`，页面会显示没有采集进程，
这是数据不会自动更新的事实。以上命令都不启动仿真。

## 能抓到哪些信息

| 获取方式 | 可核对的信息 | 样例中的具体结果 |
|---|---|---|
| `status` | 状态、关注规则、日志给出的进度、错误摘要、参考运行新增键 | `demo-warning` 为 26 ns / 100 ns；3 条示例规则命中 |
| `show` | 原生级别、编号或无编号组键、已打印次数、逐组抑制、首次时间与占比 | CMI-2753 为 WARNING，2 次，之后被抑制，首次 20 ns / 20% |
| `evidence` | 已保存原文、消息头、文件路径、行号与字节偏移、相关续行及抑制行 | 首条 CMI-2753 在 `warning.log:4`，头行在第 3 行；原文保留 Vds=1.2 V 和限制值 0.99 V |
| `measurements` | 测试台报告的 frame/code/valid；无法解析时保留 issue 与原文 | 0/23/1，1/24/0；第三条为 `short_record`，保留 `R4MEAS,2,short` |
| `details` | 原生结尾与全局抑制汇总、state/logStatus/raw 检查、请求与生效设置 | 请求 gear2only，生效 trap；全局 123 warnings suppressed；不把这 123 次分摊到 CMI 组 |
| `wait` | 新问题、状态/规则变化、日志过久未更新、采集错误及离线 | 需要运行中的采集器与实际变化；静态 `scan` 后无采集器时退出码为 4 |

NOTICE 即使命中关注规则也保持 NOTICE；没有头行时间的 `DEMO-99` 保持时间未知，
不会继承上一条消息的 25 ns。没有编号的 NOTICE 按正文数字掩码归组，原文仍保留。
测量页共有 3 条记录，其中短记录不代表一帧已成功解析；valid 只是测试台原值。
工具不从这些事实推断电路原因，不判断 ADC 正确码，也不做频谱或杂散分析。
