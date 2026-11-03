# 原生 Spectre 测试 — 2026-11-03

本轮准备16个独立案例，已有14个实际执行并完成回收；语法错误与补充的无波形超时例仍排队。不是把合成字符串当原生日志。已执行案例的原始日志保存在各自 managed 运行目录，脱敏副本与散列在 `tests/fixtures/live_20261103/`。

环境：Spectre 21.1.0.509.isr12，Spectre X CX（小测试1线程）/MX（ADC4线程），服务器账户经核对；无 OA 操作。应用工作树为 v0.4.0/API4/schema3，包含本轮修正。ADC 原始输入、PDK、共享库和历史结果保持只读。

## 已实际执行

| 案例 | 原始结果 | 工具核对结果 |
|---|---|---|
| `rc-normal` | exit0、目标tran PASS、0 errors；真实54,470 B ASCII raw完整 | complete；END/20ns检查通过 |
| `model-missing` | SFE-23，exit2 | failed，模型/子电路错误原文可定位 |
| `param-missing` | SFE-1997，exit2 | failed，参数错误及续行保留 |
| `include-missing` | SFE-868，exit2 | failed，文件读取错误保留 |
| `ahdl-compile` | VACOMP-2212/1647，exit2 | failed，VA源行与原始编译消息保留 |
| `topology` | 刚性支路闭环FATAL，exit2 | failed，无编号FATAL也提取 |
| `dc-nonconv` | SPECTRE-16080，exit1 | failed，不能把tran尚未开始当完成 |
| `tran-minstep` | 5.00081ns处SPECTRE-16927，exit1；同时有无编号Newton NOTICE | failed；进度25.0%；NOTICE保留原级别且可命中规则 |
| `soa` | 1.2V/0.99V限制，CMI-2751..2755各打印5次后抑制；exit0 | complete与SOA问题共存；带符号值、首次未知时间、抑制均保留 |
| `tb-records` | Spectre实际打印4条R4MEAS、1条FAIL、1条PASS | 6条测量；valid=0、短记录、显式FAIL共3组TB问题；无正确码推断 |
| `output-limit` | 1MiB单次运行输出限额；SPECTRE-27/7082、FATAL；进程exit0但managed为limit_exceeded | failed；exit0未掩盖失败 |
| `wall-limit` | 原意测试8秒超时，实际先碰8MiB文件限额，elapsed约3.10s | 正确识别输出失败；**不是超时覆盖证明** |
| `adc-a-tt` | 0.9V/27°C、359ns、MX4线程，三帧valid=1，码231/44/183；exit0 | complete，3条测量；无CMI，其他原生警告保留 |
| `adc-b-tt` | 相同外部条件，三帧valid=1，码231/44/183；exit0，五类CMI | complete，3条测量与SOA问题分开；相对A新增的五类CMI正确列出 |

A/B原DUT、外周TB、标准库include和observer的SHA256均与原冻结FFT运行相同；只把本次顶层stop从103259ns缩到359ns。没有更换架构或采样时钟。日志中的method请求gear2only、生效trap分别呈现。三帧一致不是全码、FFT或PVT验收。

14例最高观测RSS约370.48MiB。managed小证据回收总计217,472 B，另有RC raw 54,470 B；没有下载ADC大波形。库/仿真缓存仍留在本次独立远端目录，没有清理历史。

## 真实测试发现并修正的五处问题

1. 排队时还没有spectre.out：原来覆盖掉明确的managed queued/rejected状态。现在保留已绑定状态；没有任何证据仍为unknown，只有complete状态而无日志仍为incomplete。
2. 清单只有expected_stop_s、未配置raw：原来把未要求的raw检查当缺数据。现在只有配置raw才要求其结束时间证据；显式配置的raw缺失仍不完整。
3. 数值失败后出现“accumulated from time = 0 s”：原来把已到5.00081ns的进度退回0。现在保存本分析已明确记录的最大时间，新分析重新开始。
4. 真实Spectre进度前缀与FAIL/PASS同一行：原来漏掉显式TB FAIL。现在与R4MEAS一样识别已观察的进度前缀，普通句子中的FAIL不匹配。
5. 规则跨多组汇总时，原来优先挑有时间的后续命中：会隐藏更早、未报时间的IC期SOA。现在首条证据与其时间保持绑定，未知时间不补造。

修正位于现有parser/integrity/store，没有增加管理层或仿真控制接口。5个新增真实语料回归方法覆盖14例及原文/散列；另补必要边界正反例。完整测试套件本轮末次85项通过，原有8组历史真实日志仍通过。

## 流式、返回和页面

- 服务器默认环境未找到可用Python3，因此用外部测试适配器经已授权SSH每次增量读取最多64KiB/日志，应用读取本地追加镜像；未向产品添加SSH或远端作业控制。状态文件与logStatus也是原始副本。镜像是外部传输，不代表服务器已安装本工具。
- 采集期间实际记录到ADC running→complete、数值失败和限额失败；最终原文与managed回收副本核对。
- 用本轮原生SOA日志做流式回放：半行不唤醒，完整行可见后约0.224s，wait返回CMI-2752及规则命中。这个数值是本地采集响应，不是Spectre到本机的全链路延迟。
- 回放采集器停止后，status明确collector离线，wait返回退出码4。
- Edge实际打开16个运行，点击minstep原文、6条TB测量、3条ADC测量均正常，未出现JS异常；默认不请求原文或测量明细。截图和回执位于私有工作目录。
- 实际RC raw的截断副本和错误analysis配置都被识别为incomplete。这是对真实输出副本的受控完整性测试，不算新增原生仿真失败。

当前测试页面：`http://127.0.0.1:50147/`。Agent：

```text
python -m simcheck --db .runtime/live-spectre-20261103/validated.sqlite status
python -m simcheck --db .runtime/live-spectre-20261103/validated.sqlite show tran-minstep
python -m simcheck --db .runtime/live-spectre-20261103/validated.sqlite evidence eID
```

eID从show获取。实时检查点为 `.runtime/live-spectre-20261103/campaign-status.json`；原始集合、源绑定、回收与测试回执位于同一目录。证据句柄只属于该数据库。

## 待完成和边界

`syntax` 与 `wall-nooutput` 尚未越过CPU门禁；后者关闭波形输出、6秒墙钟上限，目的是补充真正的wall_time_limit证据。队列仍使用既有条件；有限时镜像/回收辅助进程会保存终态或拒绝回执，不重提、不改规格。完成后需要复核原文再加入黄金语料，不能提前计为通过。

本次只获准对一个1线程小测试临时放宽CPU门槛，实际用于rc-normal。核对其余14例后，跳过已经结束的13例，仅按进程身份暂停syntax的排队worker，没有停止仿真子进程。原CPU/线程/槽位策略在finally中按原字节恢复，再恢复排队worker；SHA256仍为 `2b600b9ce3eebaa611e924c8d7cc5cc4e11a0c211d20302b91f4e6307eb2ddfb`。其他已执行案例是在负载自然下降后按原门禁启动。

没有制造全机OOM、磁盘耗尽、swap或共享许可证故障；这些类别仍依赖已有历史真实fixture/边界测试。未验证其他Spectre版本、二进制PSF和无限多并发运行，不能称穷尽覆盖。
