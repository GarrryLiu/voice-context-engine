# 连续语音与开口打断

连续模式与原来的录音上传模式并存。页面点击“开始连续对话”，实时转写连接确认后才
申请并连接麦克风；开口后自动停止旧播放，停顿后提交本轮并生成回复。“结束连续对话”
关闭麦克风和转写连接，同时中止当前回复。切换分支前需先结束连续模式。

## 当前架构

```text
麦克风 → AudioWorklet（设备采样率 → 24 kHz PCM16，客户端 VAD）
       → 本地鉴权 WebSocket → OpenAI Realtime transcription
       → partial 显示 / final 按 epoch 写 transcript + outbox
       → /api/reply 校验已落库 transcript 与 epoch
       → 文本 LLM → C++ UTF-8 分句与有界播放队列 → 分段 TTS
       → 浏览器 WebAudio → ended ACK → 已播放片段可恢复
                         ↘ Kafka relay / worker → 版本化记忆
```

实时转写使用 `gpt-live-transcribe`，文本模型沿用 `.env` 的 `LLM_MODEL`，TTS 仍为
`gpt-4o-mini-tts` / coral。此接口配置使用客户端提交，`turn_detection: null`，
不是服务端 VAD。partial 可以增量显示，但不保证供应商一定在提交前发出；本次真实
中文样例只观察到 final。后台记忆不阻塞 final 对当前上下文的可见性。

VAD 和重采样目前在浏览器 AudioWorklet，实时 STT 桥接在 Python；C++ 继续负责现有
输出分句、代次检查和有界播放队列。本轮没有新增 C++ 输入设备驱动或宣称 C++ 加速收益。

## 取消、顺序与边界

- 开口检测：20 ms 帧，连续 3 帧 RMS ≥ 0.018 触发；最多 200 ms pre-roll；
  RMS < 0.012 持续 600 ms 提交。静音不上传。20 秒强制切段，包含 pre-roll。
  固定阈值是初始参数，尚未在真实噪声、口音或扬声器回声上调优。
- 本地检测到开口先清理播放、取消旧 HTTP 请求，再通过 WebSocket 通知服务端推进
  epoch。旧线程的音频读取与退出清理均检查归属，不能消费或取消新代次。
- 每个供应商 committed item 关联当时的 epoch；乱序或重复 final 不会落到当前分支。
  新一次开口、手动中断或分支切换会使尚未确认的旧 final 失效；不自动重放旧任务。
- 最多 4 个 HTTP 供应商工作线程。旧调用无法硬抢占时，后台等待其退出并保留额度，
  其余额度允许新一轮工作；全部占满时明确返回 busy。没有无限创建线程。
- 最多 4 个本地 session handle、2 个实时转写连接，且每 session 仅一个实时连接。
  每连接流式阶段最多 120 秒、32 个提交、8 个未完成 item，PCM 总量最多 5.76 MB；
  每 PCM 消息最多 9600 字节，每轮最多 960000 字节。
- Worklet 最多 10 个未确认 PCM 帧，浏览器 WebSocket bufferedAmount 上限 64 KiB，
  超限关闭采集并提示重试；上游事件与 WebSocket 接收队列也有界。断线不透明续传。
- WebSocket 单独检查 Host、Origin，并在首条消息验证页面 token；API key 仅留在服务端。
  原始音频不持久化。final 和确认播放记录保留在数据库。
- 实时 STT 每连接预留 1 个声明预算单位，沿用现有非美元 admission。model_calls 记录
  连接状态、本地 PCM 秒数及供应商返回用量；中途退出可能无法获得完整计费用量。

## 验证与已知限制

最终完整回归 **120 / 120 通过，无跳过**，含本地 PostgreSQL/Kafka/Redis、C++ 和浏览器。
[迭代记录](../experiments/continuous-voice-validation.json) 保留中途失败：曾在 epoch abort 后
提前结束读取，漏发 terminal error；已增加部分音频输出后报错的回归并修复。

自动测试涵盖：16/24/44.1/48 kHz 输入重采样、静音不触发、长语音切段、主线程不回应
时采集队列停止增长、WebSocket 鉴权与尺寸、已确认 final 立即可恢复、过时 final 不
跨分支、重复 reply 不重复调模型、旧模型忽略取消时新请求完成、旧退出清理不影响新采集。
无头 Chrome 用两段合成麦克风语音验证自动分句、开口停止旧播放与最终播放确认。
这些测试的供应商均为 fake，不产生 API 费用。

真实中文合成录音另跑一轮：首轮正确识别并回答“项目代号是北极星。”，一个片段完成
WebAudio ACK，无页面异常。从 final 确认到首段软件排程 **3.71 秒**，生成完成 **4.45 秒**；
从点击开始到完整播放确认 **16.73 秒**，包含连接、录音本身及停顿。STT 本地发送 7.18 秒，
供应商报告 8 秒；文本模型报告 248 输入 / 12 输出 token。TTS 本地记录 9 字符、148800 PCM
字节，不能据此声称是供应商计费 token。这是单样本，不是 p95 或成本优化结论。

首次诊断实验曾在连接就绪前开始麦克风，可能丢失开头音频，测试等到录音循环第二遍才
满足预期；已改为上游配置确认后才开麦。初次与修复后记录均保留：
[初次诊断](../experiments/continuous-voice-live-initial.json)、
[修复后真实结果](../experiments/continuous-voice-live-results.json)。

真实人工收音、扬声器回声、声卡回环、噪声误触发率和并发 p95 尚未测量；建议戴耳机
完成下一轮人工验收。自动停止 source 的软件证据不等于扬声器实际停止时间。

## 复现

启动方式与 [本地语音](local-voice.md) 相同，更新依赖后重启服务并刷新页面。

```sh
.venv/bin/pip install -e '.[voice,infra,dev]'
export PYTHONPATH=src
export VOICE_RUNTIME_LIBRARY="$PWD/build/libvoice_runtime.so"
export VOICE_BROWSER_TEST=1
.venv/bin/python -m unittest discover -s tests -v
```

真实 API 实验只显式运行，使用合成的 mono 24 kHz PCM16 WAV 和本地 `.env`：

```sh
.venv/bin/python experiments/continuous_voice_live.py --input /tmp/chinese-input.wav --expected 北极星
```

浏览器可设置 `VOICE_CHROME_PATH`。脚本创建隔离临时数据库，关闭后读取审计；不触及用户
已有 workspace。实际麦克风数据不用于该实验。

接口依据：[OpenAI Realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription)。
