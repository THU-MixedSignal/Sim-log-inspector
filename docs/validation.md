# 验证记录

## 历史关闭与 HTML/JSON 另存 — 2026-11-03

每条历史提供 ↓/×，关闭状态按运行 ID/代次存在当前浏览器，可 Restore closed。
新增只读 `/api/export` 下载：HTML 静态报告或 JSON 采集快照，包含当前代次全部
已入库事件、状态/检查和原有限制；源日志和波形文件不嵌入。

当前完整工作区 79 项 unittest 通过（本任务新增 8 项导出/接口检查）：原文/位置、
unknown/incomplete/FATAL、源日志离线、503 条测量跨页、代次隔离、未知运行/格式、
不可信名称、HTML 转义/下载/Host/只读方法。node --check 和 git diff --check 通过。
6 次 CLI、16 次 HTTP 请求通过；首末等六条证据及所有导出事件与原脱敏日志一致。

浏览器实测 1440×850/375×812：关闭非当前项、关闭当前项、刷新保持、全部六项关闭
再恢复、菜单键盘操作与窄屏焦点，均正常。修正窄屏菜单受滚动条遮挡的问题。两种
格式均经页面实际下载；HTML 静态内容及完整标记已核对。本地 file URL 不受应用内
浏览器支持，未做本地文件渲染，也未绕过 URL 策略。页面控制台无错误。
产物在 `.runtime/ui-history-20261103/`；仅重载已知只读查看服务，未控制仿真。

## 恢复原图紧凑布局 — 2026-11-03

用户以原图更正布局要求，本次恢复单行的级别、编号、次数、时间/百分比、tag、
正文顺序；只用字号/颜色区分主次。移除上一轮增加的字段卡片，展开直接显示
First/Last、灰色路径和原文。Rule 红框等标签及关键状态保留。

68 项 unittest、node --check、git diff --check 通过；6 次 CLI 命令、14 次 HTTP
请求通过，六条原文/位置与源文件一致，failed/unknown/incomplete 状态保持。
浏览器核对 1440×850 桌面、375×812 窄屏及五条全部展开，无横向页面溢出；
First/Last 切换、抑制行、键盘焦点及规则/参考提示正常，无控制台错误。
产物在 `.runtime/ui-compact-20261103/`。采集/解析/CLI/API 和源日志未改动。

## 问题列表与展开区对齐 — 2026-11-03

问题编号/正文共享列宽；次数、首次时间和 Rule/参考/New 标签各有固定位置，
缺失字段不使后续字段前移。展开区统一为基础字段、补充说明、来源/首末切换、
原文框。保留英文白色主题、红色 Rule 等描边标签、原生级别与原文。

68 项 unittest 通过；node --check、git diff --check 通过。6 次 CLI 命令和
14 次 HTTP 请求通过，核对五个问题组及首/末共六条证据的原文/位置与源文件一致；
Failed、Unknown、Incomplete 状态保持。

浏览器检查 1100×820 桌面与 375×812 窄屏，五条问题全部展开，无页面横向溢出。
DOM 坐标核对编号、正文、首次时间、Rule/参考标签以及展开区路径/原文框的横向
位置一致；窄屏统一纵向排列并换行。核对 First/Last 的原文、抑制行与焦点保持，
测量原文展开正常。产物在 `.runtime/ui-alignment-20261103/`。仅使用既有合成样例，
未修改采集/解析/CLI/API 或源日志。

## GitHub 发布与冷克隆验证 — 2026-11-03

用户明确授权整理提交并发布 GitHub；已创建私有仓库
https://github.com/chenzc24/spectre-log-inspector，origin 使用 HTTPS。只纳入应用、
说明、已脱敏真实样例及合成样例/来源、测试；本地 .claude 配置、原始私有日志、
数据库、运行状态和构建产物留在忽略目录。检查当前候选内容及 103 个历史 blob，
未发现常见凭据模式或历史私有/运行产物文件；不在记录中打印凭据内容。

68 项 unittest 通过。7 次 CLI 检查扫描 8 组真实脱敏样例和 6 个合成案例，状态、
原文位置、测量、不完整结果及 wait 离线退出码符合预期；11 次 HTTP 请求通过。
离线 pip wheel 构建及包资源/入口/零第三方运行依赖核查通过；node --check、
git diff --check 通过。浏览器核对当前界面和展开原文的级别、规则、抑制范围、路径
行号，控制台无错误。该检查不增加真实 SSH 或运行中 Spectre 的验证范围。
输出记录在 `.runtime/github-publish-0ktlyzy2/`。

**已推送并冷克隆**：main 的应用提交 `6c04eac254fcaaf96cc82d6c06916f32df97cbac`
从 GitHub HTTPS 克隆到仓库外的空格路径。清除源路径环境变量，使用 Python -S，
核对 import 来自新 checkout；14 组样例状态正确，68 项测试全部通过，无需 pip
安装或当前机器的原源码目录。GitHub 元数据确认仓库 PRIVATE、默认分支 main。
随后并行界面任务完成 Rule/参考标记的边框恢复，本次复核显示/原生证据/控制台，
连同收尾记录一起提交；这项调整不改变采集、解析、CLI 或 API。

## 正文优先与界面删重 — 2026-11-03

合并采集状态为一处，删除页头重复问题计数、规则名单与侧栏百分比；进度集中在
时间轴附近。问题正文优先占宽并允许两行，15px 深色；次数、首次时间和规则/参考
标记为 12px 灰字，单次打印不反复显示 ×1。展开后保留原生级别、打印/抑制范围、
首次时间、规则名、参考运行、来源路径/行号及原文。测量页使用轻量 View/Hide 按钮；
First/Last 与测量展开保持键盘焦点。英文、白色和关键状态保留。

**自动检查**：最终 `python -m unittest discover -s tests -v` 68 项通过；
`node --check simcheck/web/app.js`、`git diff --check` 通过。5 次 CLI 命令和
9 次 HTTP 请求通过，接口原文相等，failed/unknown/incomplete 状态保持。

**页面检查**：应用内浏览器 1100×820 桌面、375×812 窄屏均无横向溢出；计算样式
核对正文 15px、辅助 12px，白色主体。桌面 CMI-2753 正文含限制值可完整显示。
窄屏改为原生运行选择器，区域实测 56px；修正了单列网格把空余高度分给选择器的
问题。核对键盘 Enter 展开、First/Last 与抑制行、规则/参考信息、测量原文及焦点。
100% 无结尾仍为 Unknown，缺 END 的 raw 仍为 Incomplete evidence，FATAL+exit0
仍为 Failed；这些状态用明确文字和高对比色保留。页面无控制台错误。

检查使用既有合成样例；8 组真实语料仍由完整套件回归。通知权限未请求，未修改
采集器、解析器、CLI/API 或源日志。产物位于 `.runtime/ui-hierarchy-09o5es0n/`：
`unittest-final.txt`、`smoke.json`、`dashboard.jpg`、`mobile.jpg`。

## 仓库链接冷启动与 SSH 配置说明 — 2026-11-03

**源码冷启动**：将已提交 HEAD `4d18835afadcbacd8462c5b7b572d2bbc9b69e7b`
以本地 Git 传输克隆到仓库外的空格路径，清除 PYTHONPATH/PYTHONHOME/SIMCHECK_DB，
用 `python -S -m simcheck` 排除 site-packages 依赖。无需 pip，版本命令和 8 组
已跟踪真实样例扫描成功，完成/失败状态全部符合预期。这验证已提交源码的启动能力；
不是外部仓库 URL、远端权限或 Linux 的验证。未提交说明/修复不会进入这个克隆。

**文档调整**：README 和 AGENTS 指向仓库优先的 Agent 上手流程；补充 SSH 连接与
Git 权限/运行清单的边界、远端采集和 SSH 会话寿命、同端口转发以及模板。仅改文档
和无凭据配置样例，没有增加 SSH 连接代码或改动用户的 .ssh 配置。

**SSH 模板**：使用本机 Windows OpenSSH 执行 `ssh -G -F examples/ssh_config.example
spectre-box`，检查示例 hostname/user/port、BatchMode、IdentitiesOnly 和严格主机
校验。只解析指定模板，没有连接主机，没有读取/写入私钥或改变已信任主机列表。
真实登录、跳板机、转发策略、服务端 Python 和日志权限仍需在授权环境实测。

**回归**：68 项 unittest 通过；复用现有本地查看器完成 10 次 HTTP 检查（状态、
原文、测量、完整性、资源、Host 403）。浏览器刷新后六个案例可见，控制台无错误；
界面另有并行任务在修改，本次没有改布局或对其完成状态作保证。`git diff --check`
通过。记录在 `.runtime/repo-onboarding-lq1rwi7b/`。无仿真操作、无远端连接、无
commit/push；当前本地仍未配置 Git remote，发布入口本身尚未验证。

## 可迁移交付 — 2026-11-03

**发现并修复**：原 `pyproject.toml` 已声明 console script 和页面资源，但从仓库实际
执行离线 `pip wheel --no-build-isolation --no-deps --no-index` 失败，原因是自动发现
到 `plan` 与 `simcheck` 两个顶层包。显式限定应用包为 `simcheck` 后，同一命令成功。
wheel 包含 CLI 和 3 个页面资源，未声明第三方运行时依赖。增加离线交付打包脚本及
安装/Agent 契约；没有新增 MCP、公开发布、上传、commit 或 push。

**接收方实测**：在仓库外的系统临时目录（路径含空格）解压交付 ZIP，创建全新 venv，
用 `pip install --no-index --no-deps` 安装 wheel。在另一工作目录运行安装后的
`simcheck.exe` 及隔离模式 `python -I -m simcheck`，确认模块来自该 venv 的
site-packages，未通过当前源码/PYTHONPATH 工作。11 次安装/CLI/模块检查通过，
6 个搬迁样例状态、原文行号、测量和完整性结果保持一致。接收方不需要 Git 或源码。

**安装版链路**：通过安装版 CLI 启动采集和 HTTP，11 次请求验证 health、页面资源、
show/evidence/measurements/details、403/404；在接收目录追加一条专用合成日志，
`wait` 返回新 WARNING，show 中的规则命中及原文位置正确。此处仍是合成追加测试，
不是运行中的真实 Spectre 实机验证。只终止这次创建的监测进程。

**页面**：应用内浏览器打开安装版的独立 `serve`，六个案例加载，展开原文定位到
搬迁后的目录；截图检查桌面布局可读，控制台无错误。未将本次检查算作全平台或
完整响应式矩阵验证。源码中的英文/白色界面工作由另一个任务负责，没有在这里改动。

**回归与交付范围**：68 项 unittest 全部通过（新增 3 项：样例搬迁后结果、拒绝
未记录的输入路径、拒绝 hash 不符的样例）。`git diff --check` 通过。ZIP 仅含 wheel、
安装/Agent/API 说明、清单模板、6 个合成案例、来源和 hash；不含真实日志、数据库、
运行状态、凭据或 Python 解释器。BUILD.json 记录源码快照 hash，FILES.sha256 和
ZIP 外的 SHA-256 校验文件用于完整性核对，不是签名。审计输出位于忽略目录
`.runtime/portability-20261103-3535xnja/`。当前安装实测 Windows/Python 3.13，
Linux/macOS、最低 Python 3.10 和真实 SSH 链路尚未验证；wheel 的平台无关标签
不等于这些环境已通过测试。原始日志/PDK/ADC 脚本和仿真始终未动。

## 英文界面与白色主题 — 2026-11-03

页面控件、状态、提示、ARIA 名称、时间标签、浏览器通知文案统一为英文；固定浅色
配色，body 和主区域为白色，侧栏为浅灰色，系统深色偏好不再覆盖。原始日志证据与
用户定义值保留原文。Pause updates / Resume updates 明确表示页面刷新动作。

`node --check simcheck/web/app.js` 通过；最终完整 unittest 套件 68 项通过，包含
另一 worker 同期新增的 3 项分发测试。此前完整运行中的拒绝 POST 用例出现 Windows
10053 连接中止；该用例改发空 POST，仍验证 HTTP 501，未修改服务端。5 次 CLI
命令、9 次 HTTP 请求通过，核对证据内容及 unknown/incomplete 状态保持一致；
实际提供的三份页面资源不含中文界面文本。

应用内浏览器检查 1100×820 桌面、375×812 窄屏：body/main 计算背景均为白色，
无横向溢出；核对问题展开、First/Last、抑制原文、Measurements 的 valid=0 与
short_record、Details 的 requested/effective 与完整性信息、Pause/Resume。
浏览器通知权限未请求。产物在 `.runtime/ui-english-light-hp7xjjkx/`：
`unittest-final.txt`、`smoke.json`、`dashboard.jpg`。本次只修改界面资源、说明记录
和上述测试请求；无仿真操作，无 commit/push。

## 重构验证审计与合成案例 — 2026-11-03

**历史记录核对**：本文件与 `plan/log.md` 分别记录 v0.1/v0.2/v0.3/v0.4
的 22/24/52/57 项测试，以及 CLI、HTTP、页面检查。Git 当前可见 v0.3、v0.4
两个提交；v0.1/v0.2 的依据为实施与验证记录。不能据此独立证明每个 worker 的每次
重构后都运行过验证，也没有把这些历史数字算作本次重新执行的结果。

**本次基线**：运行规定的完整 unittest 命令，57 项中 1 项报错：外部 Host 校验测试
收到空响应，JSON 解码失败。对照实测显示，环境存在 HTTP 代理，默认 urllib opener
收到代理生成的空 HTTP 502；`ProxyHandler({})` 直连本机得到预期 JSON HTTP 403。
仅修改测试请求为显式直连并设置 5 秒超时，服务端 Host 校验和解析器保持原样。

**最终测试**：`python -m unittest discover -s tests -v` 65 项通过。新增 8 项固定核对
6 个合成案例：来源/hash、六种场景的状态、FATAL 与 exit 0 冲突、带/不带时间的
消息、NOTICE 级别、未知编号、已打印次数与抑制分离、原文行号/字节偏移、测试台
invalid/截短记录、设置差异、raw 完整/不完整、分析名不匹配、重扫幂等和输入不变。
所有样例均为手写，没有启动模拟器；入口与边界见 [样例说明](examples.md)。

**本次冒烟**：对独立临时库执行 13 次 CLI 调用、16 次 HTTP 请求，检查
status/show/evidence/measurements/details 的结果一致、health 正常、3 个静态资源
可取、外部 Host 返回 403、未知 run 返回 404；没有采集器时 wait 退出 4。
页面通过应用内浏览器检查：六个运行及状态、时间轴、原文展开与路径行号、测量的
valid=0 和 short_record、requested/effective 对照、raw 缺少 END 与结束时间不足。
默认深色桌面布局可读，页面错误日志为空。未重新做完整浅色/窄屏矩阵或通知权限测试。

**产物与边界**：临时输出位于忽略目录 `.runtime/audit-20261103-kt57edu1/`，
含 `examples.sqlite`、`status.txt`、`evidence.txt`、`smoke.json`、`unittest.txt`。
`git diff --check` 通过，新增非 fixture 文件也检查了空白。本次未重新扫描私有
原始日志；8 组既有脱敏真实语料由完整测试套件回归。真实 source log、PDK、ADC
脚本及仿真均未修改；无 commit/push。新增合成样例不构成新厂商格式或全波形验证。

## v0.4 执行 Agent 为主要读者 — 2026-11-02

**测试**：`python -m unittest discover -s tests -v` 57 项通过。新增覆盖：status 对 8 组示例日志小于 5 KB 且没有 null、false 或空集合；运行排序（失败、命中规则在前，正常结束且无关注的在最后）；失败运行按日志顺序给出首个错误（minstep 为 SPECTRE-16927 @1.14929ns，output_limit 为 SPECTRE-27 与 SPECTRE-7082）；show 默认隐藏未命中规则的 NOTICE 组并给出数量；新问题组命中规则时只产生一条变化；wait 结果不附带运行摘要并给出下一条命令；文本中的句柄与 path:line；`SIMCHECK_DB`；`--json`、`--db` 写在子命令前后都有效；格式不对的句柄被拒绝。

**体积**（8 组示例日志，同一数据库）：status 文本 2368 B、JSON 3690 B（v0.3 JSON 约 17.9 KB）；show minstep 1036 B，show noise 2475 B（12 行）；evidence 454 B；details 661 B；measurements（20 条）475 B；一次 wait 结果 209 B（v0.3 附带完整运行摘要）。

**端到端**：`watch`（间隔 1 秒）、`status`、`wait --cursor`：日志追加一条 CMI-2753 后 1.26 秒返回一行 `new WARNING … rule=SOA` 和下一条 wait 命令；再次 wait 无新内容，超时退出 3。

**页面**：去掉说明文字、图例、规则和参考对比区块、时间戳、页脚；标签页为问题、测量、详情；问题一组一行，`×5+` 表示之后被抑制。1100×820 浅色和深色、375×812 窄屏无横向溢出，无控制台错误。

**未覆盖**：真实浏览器通知权限弹窗仍需人工开启；PSF raw 头尾检查仍只有合成样本。

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
