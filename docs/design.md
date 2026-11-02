# 设计方案（v0.3）

## 目标
在仿真进行中尽早让人和 Agent 看到已经出现的问题证据，避免无效仿真占用时间。衡量标准是**发现延迟**（问题行写进 spectre.out 到有人被告知）和**召回**（早期信号是否被抓到）；节省阅读量只是顺带的效果。少分类、不猜原因、可回归验证；部署独立，不侵入仿真流程，不停止仿真。

## 分层与所有权

```text
只读 manifest -> spectre.out + 可选 state/logStatus/raw 头尾
                        |
           collector（run/watch）：增量读取、游标、心跳
                        |
           parser：头行块、原生消息、notice、抑制、设置、测试台记录
                        |
         SQLite WAL（单写者）+ integrity 有界检查
                 /                    \
      CLI JSON / wait / report     只读 HTTP API -> 浏览器（提醒）
```

parser 不访问文件系统；store 不作电路推断；integrity 只合并显式证据；server 只读打开数据库，不操作源文件。全部代码局限本仓库。

## 采集
`run` 前台采集加网页；`watch` 与 `serve` 可分开运行。`run` 先绑定端口再采集，端口被占用时直接报错。每轮每个运行最多 2 MiB、单行 64 KiB；落后时连续处理，追平后按间隔轮询。每个运行独立 try：一个运行的 sidecar 或其他异常只记录在该运行上（`collector_error`），不阻塞其他运行。每轮写 `collectors` 心跳；正常退出时删除。

增量识别：文件身份、前缀 hash、已读边界 anchor。替换、截断、新启动段开新 generation，旧证据保留。数据库是派生索引：schema 版本不符时拒绝打开且不修改旧库。

## 解析
Spectre 用“头行 + 缩进块”打印消息：`Warning|Notice|Error|Fatal error from/found by spectre [at time = …] [during … analysis `x']`。头行开启一个块，块内：

- `WARNING/ERROR/FATAL/NOTICE (CODE):` 标签行是一条消息，级别取标签；
- 块内第一行无标签正文（Spectre notice 的形式）是一条消息，级别取头行；
- 其后的缩进行是续行；`Further occurrences … suppressed` 是对上一条消息的逐码抑制；`N warnings/notices suppressed` 是原生全局汇总；
- 非缩进行或空行结束块。

消息的仿真时间只取本块头行；头行没有时间就是 `null`。`last_logged_time_s` 单独记录日志中最近出现的 `time =`，用作进度下限。瞬态结束时间取自 `Transient Analysis `x': time = (0 s -> stop)`。未知编号保留；无编号消息按正文（数字掩码）归组。

## 完整性
ERROR/FATAL、managed 终止/限额、logStatus 最新状态 FAIL 优先判失败；正常 footer 只证明原生日志正常结束。配置了 raw 时要求 PSF ASCII、END、到达指定结束时间（头尾快速检查，不是全波形）。logStatus 是每个分析的 START→PASS/FAIL 流水，以最新一行为准。没有 footer 也没有可信状态时为 unknown。

## 早发现
- **关注原因**是事实：失败、命中用户规则、未结束且日志超过阈值未修改、采集出错、日志读取失败。
- **规则**由用户在 manifest 中写（编号通配、键通配、级别、正文子串、最少次数）；工具只报告命中，不自行决定哪些告警意味着仿真作废。
- **参考运行**：列出参考运行当前代中从未出现的键。
- **首次出现**：每组记录首条消息的仿真时间、占结束时间比例、首次被采集的墙钟时间（入库时刻）。
- **唤醒**：`wait` 在新问题组、状态变化、新规则命中、日志超时、采集出错或采集器离线时返回；页面在同样的变化上发浏览器通知并更新标题计数。

## 可视化
- 颜色只表示“请看这里”：失败与规则命中为 critical，日志超时与采集问题为 warning；正常结束的运行不着色。级别同时用形状（■ ▲ ● ◆）和文字表示，不只靠颜色；标记调色板经 CVD 与对比度校验（见 validation）。
- 运行详情的主角是仿真时间轴：进度条（下限）加各组首次出现标记；相互重叠的标记合并并直接标注“N 组，最早 t（%）”。问题列表就是这张图的表格视图。
- 原文按日志行号显示头行、消息、续行和抑制行；所有日志文本以 textContent 写入。页面就地更新，不在每次轮询时重建节点，焦点和展开状态保持。
- 浏览器 CSP 只允许同源脚本和样式（无 inline）；服务端只回应本机 Host 头。

## 演进
后续顺序：更多真实 Spectre 版本语料 → 独立 ADC 契约插件 → managed analysis-only 波形检查 → 有真实语料后其他仿真器。新分类与判断必须带正反回归样例。不会扩展到因果诊断、杂散分析、自动停止或修改仿真。
