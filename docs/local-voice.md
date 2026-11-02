# 本地语音闭环：第一轮

本轮是可使用的本地浏览器原型：点击录音、停止发送，显示流式转写和文本回复，
播放真实分段 TTS。它处理的是**录音结束后的转写流**，不是采集过程中持续上传的
Realtime STT，也还没有自动 VAD、自动检测用户打断、网络重连或硬件停止延迟测量。

## 启动

保留已有本地 `.env` 的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
服务端使用同一个 OpenAI client，STT 为 `gpt-transcribe`，文本由 `LLM_MODEL`
决定，TTS 为 `gpt-4o-mini-tts`、coral 声音，输出 24 kHz、单声道、PCM16 little-endian。
三个阶段都产生真实 API 用量；当前只记录已报告用量或本地字符/音频计数，没有美元计费对账。

```sh
.venv/bin/pip install -e '.[voice]'
.venv/bin/python scripts/build_runtime.py
export PYTHONPATH=src
export VOICE_RUNTIME_LIBRARY="$PWD/build/libvoice_runtime.so"
.venv/bin/python -m voice_context.voice_server --db voice-workspace.db --port 8765
```

打开 <http://127.0.0.1:8765>。点击“开始录音”，在浏览器授权麦克风，说完后点击
“停止并发送”。录音最多 20 秒，也可以上传 webm/ogg/mp4/wav 固定录音，最大 2 MiB。
上传的文件只按类型/字节数限制；服务端尚未解析容器做独立时长校验。

开发时应在终端启动这个进程。Codex 内置浏览器的麦克风能力取决于宿主；如果没有
权限提示或无法采集，请在本机 Chrome 打开相同地址。服务只绑定 loopback。
原始录音不落盘，最终转写与确认播放的回复保存在配置的数据库中。

默认使用单个 SQLite workspace；使用基础设施数据库可指定 `--db "$VOICE_DATABASE_URL"`
及 `--redis-url "$VOICE_REDIS_URL"`（后者只适用于 PostgreSQL）。最终发言只写 outbox，
不等待后台处理；需要记忆候选时另外启动 Kafka relay/worker，见 infrastructure.md。
网页目前没有 approve、冲突修订、历史列表 UI；候选确认沿用现有 API。

## 数据流与边界

1. 浏览器 MediaRecorder 收集一段录音，停止后通过原始 HTTP body 上传。
2. `Conversation.transcribe` 驱动 STT provider，partial 只显示，最终转写持久化并推进 epoch。
   采集队列此时传递的是编码文件字节，不是声卡 PCM，也不在 C++ 中解码输入容器。
3. 文本 provider 获得固定分支上下文，生成 delta；C++ UTF-8 分句后逐段调用 TTS。
4. PCM 以有界块进入 C++ 播放队列，HTTP 消费者通过软件 render 读取，并发 producer
   不需要等待整段回复生成。输出总量最多 2 MiB，有背压和超时。
5. 每个 PCM 块携带 request ID、epoch、序号和字节 offset，浏览器检查后创建
   AudioBufferSourceNode；排程通常最多领先约 1.5 秒加一小块。浏览器 ACK 尚未持久化前
   不开启下一轮录音，避免刚播完的回复尚未进入下一轮上下文。
6. `onended` 后 POST ack，只有完整已确认片段进入恢复上下文。刷新页面显示近期输入
   和已确认回复。**WebAudio ended 是客户端软件报告，不是扬声器物理播放证明。**

第一轮提供显式停止播放和基本分支创建/切换；录音采集时禁止切换；回复生成/播放时切换会先停止旧代次，并在切换完成前禁止新录音。
完整 barge-in、分支切换并发与断线恢复是下一轮测试目标，不能由现有按钮推定已完成。
后端只允许一个 active turn，最多保留四个 session handle；一个数据库对应一个本地
workspace，不提供多租户、远程登录或公开部署。会话默认声明预算为 100 单位，沿用
之前持久化 admission 语义，并不是 100 美元，也不会因刷新而重置。

页面 token、Host/Origin 校验和 CSP 用于限制其他网页跨站请求本地 API；不是面向
不可信本机用户的身份认证。API key 不返回浏览器，接口错误只返回类名/固定消息。
SDK read timeout 为 10 秒；取消/断连后旧输出被拒收，但阻塞中的供应商调用不是硬抢占。

## 验证结果

- 音频 provider 测试：转写 partial/final、缺失 final、取消、PCM 奇数网络碎片拼接与
  不完整采样拒绝。
- 服务测试：真实 C++ 队列消费超过队列容量的音频、显式 ack 后的恢复上下文、请求
  边界、并发限制、失败终止和 slot 释放。
- 无头 Chrome：固定文件上传、假麦克风录音/停止、WebAudio 播放 ack、刷新恢复、
  手机宽度布局；全部使用假供应商，没有付费调用。
- 真实 HTTP：macOS Samantha 本机合成固定英文录音，经真实 STT/LLM/TTS 和 C++。
  转写正确，回答 “The project codename is Cedar.”，输出 PCM 3.55 秒；首段 HTTP
  音频返回约 4.23 秒。
- 真实 Chrome 上传：初轮首段排程 3.32 秒，最终 2.84 秒；最终从上传到 WebAudio
  ended 和确认完成约 6.48 秒，服务端可读取一个已确认回复片段，无页面异常。

这些是单例功能验证；两轮间服务状态/网络时延均可能不同，不能把时间差当成优化收益。
没有人工耳听、实际麦克风、声卡回环或 p95 样本，因此不报告实际首声或打断 SLA。
后续已增加中文合成录音与故障回归，见 [自动验收报告](voice-fault-validation.md)；真实人工收音仍待验收。

原始结果：
`experiments/voice-roundtrip-results.json`（初轮源码 hash）；
`experiments/voice-browser-results-initial.json`；
`experiments/voice-browser-results.json`（最终 Python 源码 hash）。
测试录音与回复 WAV 保存在本地 outputs/voice-loop，没有提交音频或用户凭据。

## 复现

```sh
.venv/bin/pip install -e '.[voice,infra,dev]'
export VOICE_BROWSER_TEST=1
# 首次安装测试浏览器；Mac 也可设置 VOICE_CHROME_PATH 为本机 Chrome 可执行文件。
.venv/bin/python -m playwright install chromium
.venv/bin/python -m unittest discover -s tests -v
```

付费端到端实验必须显式运行，日常 CI 不执行：

```sh
.venv/bin/python experiments/voice_roundtrip.py /absolute/path/input.wav --audio-output /tmp/reply.wav
.venv/bin/python experiments/voice_browser_live.py /absolute/path/input.wav
```

前一个脚本不播放音频，故不会发送播放确认；后一个脚本使用无头 Chrome 的 WebAudio
并在 ended 后确认。可以使用本机合成音频构造可重复录音：

```sh
say -v Samantha -o /tmp/input.aiff 'The project codename is Cedar. What is the project codename? Please reply in one short sentence.'
afconvert -f WAVE -d LEI16@24000 /tmp/input.aiff /tmp/input.wav
```

实现依据：[录音转写流](https://developers.openai.com/api/docs/guides/speech-to-text)、
[PCM TTS](https://developers.openai.com/api/docs/guides/text-to-speech)。
