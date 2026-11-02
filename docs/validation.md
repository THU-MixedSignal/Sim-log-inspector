# 验证记录

## v0.3 早发现 — 2026-11-02

**测试**：`python -m unittest discover -s tests -v` 52 项通过（真实日志 8 个子案例）。新增覆盖：头行限定时间（含真实 SPECTRE-555 无时间头行）、notice 捕获与不升级、notices/warnings suppressed 汇总、逐码抑制挂在最后一条已打印消息上、瞬态结束时间与首次出现、示例规则与参考对比、日志超时只在未结束时提醒、心跳、坏 sidecar 隔离、单个运行异常不阻塞其他运行、`wait` 唤醒/超时/无采集器、token 不随观测时间变化、UTF-8 输出（µ、✓）、JSON 错误、读命令不建库、端口占用在采集前失败、旧 schema 拒绝且文件不变、Host 校验、CSP 无 inline。真实日志新增交叉校验：6 份带 footer 的日志中，带标签的 WARNING 条数与 ERROR/FATAL 条数分别等于 footer 的 warnings/errors（不依赖本解析器）。

**真实 logStatus**：本机 8 个运行中 6 个有 `raw/logStatus`（START→PASS 4 个、START→FAIL 2 个），逐字节复制为 fixture 并记录 hash；compile 与 license 在读入/许可证阶段即终止，原运行没有 raw 目录，测试中按真实情况配置不存在的路径，期望 `unavailable` 且状态仍为 failed。

**原始日志对照**：用新版本只读扫描私有 `.runtime/demo.json`（未脱敏原始日志）到临时库：8 个运行状态全部等于 golden，问题组数与各级别条数与 fixture 完全一致；脱敏没有改变解析结果。

**脱敏补漏**：8 份 fixture 的 `Configured Lic search path … port@host` 行此前未脱敏，已按行替换为既有占位行，行数不变，`provenance.json` hash 同步更新，测试断言任何 fixture 中都不再有 port@host 形式的地址。

**早发现端到端**：`watch`（间隔 1 秒）+ `wait --after --since`，在日志追加一条 CMI-2753 后 1.23 秒返回 `rule_hit` 与 `new_problem_group`；无新内容的下一次 `wait` 超时退出 3。页面实测（浏览器通知 API 以替身记录）：新规则命中、日志超阈值未更新、状态变为失败、新问题组均触发提醒；同一刷新内同一运行的多条变化合并为一条通知；终止采集进程后改用只读 `serve` 打开同一数据库，页面显示“采集器离线”横幅并给出数据停止时间（离线判定阈值为 3 个采集间隔加 5 秒、至少 10 秒，由单元测试覆盖，未单独测量页面延迟）。

**页面**：1100×820 浅色与深色、375×812 窄屏无横向溢出；轮询期间运行列表与时间轴标记的键盘焦点保持；在时间轴标记上按 Enter 打开对应问题组；无控制台错误。标记调色板用 dataviz 校验脚本验证：浅色 `#b3123a/#c58400/#2a78d6` 全部通过（all-pairs CVD ΔE 18.0，正常视觉 23.7，对比度 ≥3:1）；深色 `#e0485f/#b7831d/#4a90e2` CVD 6.2 落在警告带，级别同时用形状（■▲●◆）和文字标注作为第二编码。正文墨色对比度：主 16.3:1、次 7.4:1、弱 5.1:1（白底）/4.7:1（页面底）。

**性能抽样**（`scripts/benchmark.py`，合成重复 WARNING，非厂商基准）：5000 事件 0.88 秒、Python 堆峰值 51,941 B、空轮询 3.0 ms；40000 事件 6.93 秒、39,455 B、空轮询 5.0 ms。比 v0.2（5.82 秒）慢约 19%，来自每条证据新增的观测时间、问题键与头行字段；堆仍不随事件数线性增长。

**未覆盖**：真实浏览器通知权限弹窗需要人工点“开启提醒”；PSF raw 头尾检查仍只有合成样本；未做多客户端并发与非 Windows 平台测试。

## v0.2 摘要与分流验证 — 同日
在既有真实日志回归中核对分流后的完成状态、测量数量、CMI已打印次数及证据原文；没有新增电路判断。24项测试通过（包含8组真实日志子案例）；新增两个用例检查分流/历史代次/异常TB归组和旧库升级不改变证据ID、不重复采集。既有HTTP测试补充v2摘要与按需证据。

CLI status/problems/measurements/evidence均实测。Edge页面显示8个运行，noise的10组原生问题；首次加载不请求测量、原文或详细设置，点击后分别返回原文、20条测量与设置，无页面JavaScript异常。截图.runtime/summary-dashboard.png。

同一组本地实际日志：默认/api/runs由此前22269 B降至约8655 B；按需100条测量为11886 B，旧100条完整事件约82053 B。不同返回契约的体积对比，不是模拟器加速或内存RSS基准。

新版查看器127.0.0.1:8766，使用独立.runtime/summary.sqlite；旧8765进程未终止。Windows同端口复用曾使页面连到旧接口，已改为排他绑定。页面验证脚本的CSP字符串等待写法已换为locator断言，没有放宽CSP。无仿真流程变更。

环境：Windows、Python 3.13；运行时标准库；SQLite。新仓库独立开发，现有ADC代码和仿真均未变更。

## 真实语料
8组脱敏日志及状态：A/B无噪声FFT、B含噪声FFT、B静态末段、minstep失败、VA编译失败、输出限额失败、license失败。
每份有原始hash和脱敏hash，行号保留；测试固定核对完成/失败、1032/285帧数、CMI25条、抑制总数、requested gear2only与effective trap、Vgd带符号值及时间。没有声称这些语料覆盖全部Spectre消息。

## 测试
`python -m unittest discover -s tests -v`：22项测试通过，真实语料测试包含8个子案例。
包括逐字节/中文µ单位、半行、重新打开、截断和同长度替换、追加启动段、多analysis状态、exit0+fatal/限额、raw头尾/stop、不支持格式、超长行、未知code、无oracle、HTTP只读及文本安全。

测试中发现并修复：
- R4MEAS valid字段索引需按实际格式取第8项，不能凭印象。
- 原始进度字符与R4MEAS同一行；只匹配行首会漏掉约70帧。现在保留整行并识别进度前缀。
- Windows SQLite连接必须明确关闭，否则HTTP读连接会持有文件句柄。
- fixture脱敏必须逐行精确处理，不能把早期license块之后整段仿真输出误删；hash按实际字节计算。

## 性能抽样
`scripts/benchmark.py`：本机合成重复WARNING写入SQLite，开启tracemalloc；不是厂商运行基准。

| 源字节 | 事件数 | 扫描秒数 | Python堆峰值 | 无新增轮询秒数 |
| ---: | ---: | ---: | ---: | ---: |
| 340000 | 5000 | 0.903 | 65281 B | 0.0029 |
| 2720000 | 40000 | 5.822 | 42875 B | 0.0046 |

这是Python可追踪堆，不等于进程RSS；SQLite原生内存和OS缓存另计。事件数8倍增加没有造成Python堆线性增长。磁盘存储仍随事件数增长，v1无自动删除策略。

## 可视化
通过本机Edge headless打开实际HTTP页面，8张运行卡片加载，选择noise和diagnostics后显示37条事件；未出现JavaScript异常。截图人工检查可读性。页面只读，2秒刷新；原文用textContent。临时截图和实际私有运行索引留在.runtime，不发布。

## 限制
未做大规模并发客户端或所有平台测试；不支持二进制PSF、全raw峰值/时长、任意工具版本、ADC独立正确码oracle、SSH自动采集和生产managed替换。源文件中间原地静默修改不能通过增量首尾fingerprint全面识别。已知界限在README和schema中明确。
