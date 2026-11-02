# 语音运行层与上下文闭环：实现与实验

日期：2026-11-01。PR #7；本轮是可运行的本地纵向切片，不是完整上线的语音产品。
完整需求和未实现部分见 [产品范围](product/voice-workspace.md)。

## 已落地的行为

- 最终转写与 outbox 同事务持久化；后台未执行，当前上下文已可读取。
- fork 保留当时的记忆和发言视图；支持近期发言撤回、版本化记忆修正和历史。
- session/branch/epoch/request/context revision 约束回复；打断、切换、重连与新发言
  使旧输出失效。回复正常结束也会封口，已排队音频仍可消费。
- C++17 线程安全有界队列、UTF-8 分句、连续音频序号、部分 render 和软件取消。
- STT/text/TTS Protocol、provider 身份、阶段声明预算/耗时/状态、输出 byte cap、
  协作 deadline 和播放背压。供应商调用在协调锁外执行。
- render 与播放 ack 分开；ack 单调、持久，并限制在已 rendered 的范围。
  只有完整确认已播的 assistant 片段进入恢复上下文，不自动写成长时记忆。

## 多轮优化

初始 C++ 扫描每次重新验证和扫描 pending 前缀，Python binding 每次 pop 又分配
大缓冲。先保存初始结果，再加入增量 UTF-8/扫描位置、ASCII 快路径和可复用 FFI
读缓冲。默认使用增量路径，同时保留 rescan 模式作同版本对照。

下面是最终同一实现、相同 chunk 与字节输入的五轮实验；每轮每配置五份文档。
记录值是轮中位数的中位数，单位微秒/文档。包含 ctypes、锁、复制和 pop。

| 输入 | Python regex 参考 | C++ rescan + binding | C++ incremental + binding | rescan / incremental |
| --- | ---: | ---: | ---: | ---: |
| 312B 短句 | 27.71 | 106.79 | 107.62 | 0.99× |
| 16001B 长句 | 878.21 | 9072.25 | 2008.92 | 4.52× |
| 7503B 中文碎片 | 723.96 | 5710.46 | 1636.71 | 3.49× |

独立 C++ 可执行文件中，16001B 长句（25 样本）中位数为 7444.08us
rescan 对 286.75us incremental，约 25.96×。
它不经过 Python，也不在每个输入 chunk 后尝试 pop，不能把此数字与上表直接
做跨语言比较。增量模式避免前缀重复扫描，但仍有字符串复制和队列开销。

**负结果保留：通过绑定调用时，C++ 分句路径仍慢于 Python 正则参考。** 后者只是
有效输入的分句 fixture，不含整个音频运行层；不能据此推导完整语音产品的语言
优劣。C++ 的线程、队列、取消和设备接入价值，也不能代替性能实测。

初始结果保存为 `runtime-results-initial.json`，原生基线源对应 653c6b1；最终结果
为 `runtime-results.json`，带源码/binding hash。初始和最终变更多个因素，不把两版
差异归因到单一优化。最终同版本的 mode 对照更适合评估前缀扫描的影响。

## 恢复、并发与取消实验

最终同一份代码在同一台本地 Mac 连跑三轮。每轮 20 次正确性场景和四会话共
40 次 scripted response。STT/text/TTS 是脚本；text/TTS 插入 1ms sleep，输出是
合成字节而非音频波形。没有网络、模型推理或实际播放。

立即可见、迟到输出拒收、过时记忆拒绝、重连恢复和 outbox 去重，五类检查每类
60/60 成功。软件计时如下；p95 按各轮分别计算，不把多轮当作独立硬件试验。

| 软件计时 | 三轮 p95（ms） | 三轮 p95 的中位数（ms） |
| --- | --- | ---: |
| 控制请求到队列清空（含 SQLite） | 0.436, 0.425, 0.472 | 0.436 |
| 重新打开与恢复 | 1.743, 1.427, 1.207 | 1.427 |
| 四会话首个合成输出块入队 | 92.507, 49.159, 66.937 | 66.937 |

这不是首段语音/扬声器停止延迟。四会话 p95 明显有波动，SQLite 写争用与进程调度
是下一步值得测量的因素，当前结果不足以作因果归因或部署 SLA。

并发阶段账本每轮记录 40 次 reason、40 次 TTS，各 1 个声明单位，共 80 单位。
这些值用于检查预算、归属与失败处理，不是供应商价格；本轮没有真实费用节省
结论。STT 正确性在前面的 20 次场景验证，并发费用合计不包括这些单独场景。
每轮原始软件时间、源码 hash、各阶段声明单位都保存在 `realtime-final-*.json`。

## 验证与自审

- 73 个 Python 测试，启用真实 native library，涵盖协议、线程回调、重复/过时状态、
  版本修正、预算、输出上限、显式播放 ack 和审计失败后的本地清空。
- 两种 native 模式的 C++ 测试：UTF-8 字节切分、容量、序号、部分消费、取消、
  四 producer 并发；AddressSanitizer 和 UBSan 检查通过。不声称做了 ThreadSanitizer。
- Python 3.11–3.13 CI 会编译原生库、运行 sanitizer/native/Python 测试与模拟场景，
  并保留实验 artifact。平台上的性能数值不作 CI 门槛。
- 显式自审：检查了事务边界、版本比较、native/DB 取消顺序、FFI buffer 生命周期、
  单位命名和未实现能力。没有独立第二位评审者或真实语音质量评审。

## 复现

```sh
python3 scripts/build_runtime.py
export VOICE_RUNTIME_LIBRARY="$PWD/build/libvoice_runtime.so"
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 experiments/voice_demo.py
PYTHONPATH=src python3 experiments/runtime_benchmark.py --output /tmp/runtime.json
PYTHONPATH=src python3 experiments/realtime.py --output /tmp/realtime.json
clang++ -std=c++17 -O3 -pthread native/benchmark.cpp -o build/runtime-benchmark
build/runtime-benchmark
```

`voice_demo.py` 明确是模拟演示，不会录音、播放真实声音、下载模型或调用在线服务。
后台仍是 SQLite/outbox/leased queue；Kafka、PostgreSQL、Redis 是独立后续实现。
真正的设备回调不应直接运行包含 SQLite 的 Python `Conversation.render`。
