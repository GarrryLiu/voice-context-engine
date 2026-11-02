# 语音自动验收：中文与故障恢复

日期：2026-11-02。本轮在独立端口、数据库和无头 Chrome 中测试，未读取用户麦克风，
未重启用户正在使用的 8765 服务。付费调用只用于一例本机合成的中文录音。

## 真实中文闭环

macOS Tingting 合成输入：“项目代号是北极星。请告诉我项目代号是什么，只用一句话回答。”
浏览器上传后实际经过 gpt-transcribe、gpt-6-luna、gpt-4o-mini-tts/coral、C++ 队列
和 WebAudio。转写保留“北极星”，回复为“项目代号是北极星。”，播放结束后服务端
可读取一个确认的回复片段，没有页面异常。

本次软件记录：转写 1.93s，上传到首段 WebAudio 排程 5.17s，生成完成 5.65s，
上传到浏览器播放结束及确认约 8.67s。单个合成案例不代表中文识别准确率或 p95；
没有人工耳听、物理麦克风或扬声器回环验证。
持久用量记录：STT 报告 7 秒输入，文本模型报告 231 输入 / 12 输出 token；
TTS 本地计数为 9 字符、129600 PCM 字节，不是已核对的收费 token。
原始记录：`experiments/voice-chinese-results.json`，其 Python 源码对应测试开始时版本。

## 故障实验

`tests/test_voice_faults.py` 使用假 STT/LLM/TTS，但浏览器、HTTP、SQLite、C++ 队列和
WebAudio 都实际运行。供应商门闩故意忽略取消，制造取消后的迟到结果；用 CDP 限速
制造 16KB/s、80ms 网络，用服务端延迟制造旧 ACK 长时间未返回。没有付费 API 调用。

| 场景 | 验证 |
| --- | --- |
| LLM 生成中停止 | 迟到文本不显示、队列清空、下一轮可完成 |
| TTS 合成中停止 | 迟到音频不播放、不进入确认上下文 |
| 播放中停止 | 软件音源归零，未完整确认片段不冒充已播放 |
| 活跃回复中切换分支 | 先停止旧代次，切到 child，旧文本不进入新视图/上下文 |
| 生成中刷新 | 旧生成被废弃，重新提交可完成 |
| 离线请求后恢复 | 明确观察 failed fetch，再恢复网络并重试 |
| 流中断开 fetch | 后台最终释放 slot，新请求可完成 |
| STT/LLM/TTS 分别失败 | 统一终止，无敏感错误文本泄漏，随后可重试 |
| 播放确认失败 | 不把未确认片段写入恢复上下文 |
| 旧 ACK 延迟及失败 | 不阻塞下一轮，也不污染下一轮状态 |
| 慢网络 | 全链路正常完成，只有实际客户端 ended 后确认 |

这是 11 项带断言的场景，每项一个功能样本；不是各故障组合的完整矩阵，也不是
硬件停止延迟基准。停止指标记录的是 Playwright 点击到页面“已停止”的软件时间，
包含浏览器自动化和控制请求开销，不能当作耳朵听到声音停止的时间。
最终本地全量 110 项测试通过（包含真实 PostgreSQL/Kafka/Redis 与浏览器），11 项
故障场景全部通过。
原始结果和前后端源码 hash：`experiments/voice-fault-results.json`。

## 找到并修复的问题

初轮 9 项测试中有 1 项失败：活跃回复时分支选择器被禁用，所以不能进行目标行为。
现在允许在回复阶段切换，先停止浏览器音源及旧请求，再提交分支切换；切换期间禁止
开始新录音，录音采集期间仍不切分支。

额外回归复现了旧 ACK 的错误污染：全局 pending ACK 计数和失败标记跨回复复用，
延迟的旧请求会影响新回复的结束状态。现在清理音频时重置计数，旧 generation 的
失败/完成回调均不修改当前回复。更严格的服务端延迟测试还暴露了浏览器连接占用：
忽略旧回调仍不够，旧 ACK HTTP 请求会占用同一 origin 的连接。现在切换代次时
同时中止旧 ACK fetch，释放浏览器连接；不承诺抢占服务端已经执行的请求。新测试在旧 ACK 仍被阻塞时就要求下一轮正常完成，
再释放旧请求并确认 UI 不被它的失败改写。

中间轮全量 110 项中也保留了旧 HTTP ACK 阻塞失败：`experiments/voice-fault-results-intermediate.json`。
初轮失败与测试局限保留在 `experiments/voice-fault-results-initial.json`。其中初轮离线
检查存在过早通过的可能，最终版已加强为先断言实际 failed-fetch 状态。

## 复现

```sh
.venv/bin/pip install -e '.[voice,infra,dev]'
.venv/bin/python scripts/build_runtime.py
export PYTHONPATH=src
export VOICE_RUNTIME_LIBRARY="$PWD/build/libvoice_runtime.so"
export VOICE_BROWSER_TEST=1
.venv/bin/python -m playwright install chromium
export VOICE_FAULT_RESULTS=/tmp/voice-fault-results.json
.venv/bin/python -m unittest discover -s tests -p test_voice_faults.py -v
```

macOS 可设置 `VOICE_CHROME_PATH` 指向本机 Chrome 可执行文件。全量测试开启基础设施
测试环境变量后执行 unittest discover；CI 在 infrastructure job 中运行这些场景并上传
JSON 和截图，不需要 API key。

中文真实实验要显式启动独立测试服务，避免干扰自己的会话：

```sh
say -v Tingting -o /tmp/chinese.aiff '项目代号是北极星。请告诉我项目代号是什么，只用一句话回答。'
afconvert -f WAVE -d LEI16@24000 /tmp/chinese.aiff /tmp/chinese.wav
# 另一个终端运行：python -m voice_context.voice_server --db /tmp/chinese-test.db --port 8766
.venv/bin/python experiments/voice_browser_live.py /tmp/chinese.wav --url http://127.0.0.1:8766 --expected 北极星 --output /tmp/chinese-results.json
```

仍未完成：自动 VAD/barge-in、采集中的连续 STT、无需重试的透明断线续传、真实多人
并发以及硬件指标。当前单 active turn 会在忽略取消的供应商调用退出前保留 slot；
此间立即发起新请求可能得到 busy，需要稍后重试，不能据本轮结果宣称无缝打断重入。
