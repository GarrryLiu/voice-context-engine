# 真实文本模型：接入与实验

当前提供 `OpenAITextProvider`（Responses 流式文本）和 `OpenAIExtractor`（结构化记忆候选）。
模型由本地 `.env` 的 `LLM_MODEL` 指定，实验使用 `gpt-6-luna`。本轮基于基础设施
PR #8 的分支开发；合并顺序为基础设施在前、本轮模型接入在后。

## 本地配置

```sh
.venv/bin/pip install -e '.[infra,llm]'
```

本地 `.env`：

```dotenv
LLM_API_KEY=本地填写
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-6-luna
```

`.env` 已忽略，不纳入代码提交。进程环境变量优先于文件；dotenv 只解析配置，
不通过 shell 执行。当前适配器限制为官方 OpenAI endpoint，其他兼容服务需要独立适配。
不会在 import 时读取凭据或调用模型。

## 在产品协调层使用

```python
from voice_context.conversation import Conversation
from voice_context.openai_provider import OpenAITextProvider, ModelJournal

# db 可以是 SQLite 路径或 PostgreSQL DSN；TTS 需要调用方提供。
journal = ModelJournal(db)
text = OpenAITextProvider.from_env(journal=journal)
conversation = Conversation(db, 'session-1', publish_on_submit=False, redis_url=redis_url)
try:
    state = conversation.pipeline.sessions.get('session-1')
    conversation.pipeline.sessions.submit(
        'session-1', 'utterance-1', '我们继续讨论数据库选择。', state['epoch'])
    conversation.respond('reply-1', text, your_tts_provider)
finally:
    conversation.close()
    text.close()
    journal.close()
```

实时 STT/TTS 和实际设备还未接入；现有 scripted provider 可以验证队列，但不是语音。
`Conversation` 仍负责会话代次、输出上限、队列背压和旧任务隔离。
provider 实例按单个执行流使用，不应被多个并发会话共享；ModelJournal 自身支持
跨线程串行写入，每个后台 worker 也有独立连接与 SDK client。

## Kafka 后台记忆提取

沿用 [基础设施启动说明](infrastructure.md)，将 worker 改为：

```sh
PYTHONPATH=src .venv/bin/python -m voice_context.broker worker --openai --env-file .env
```

未传 `--openai` 仍是规则模式；显式启用才会产生 API 用量。
worker 使用 JSON schema 请求候选，再检查 evidence 是原文子串、value 是 evidence 子串。
提取器返回空候选是有效结果。拒绝、截断、无效来源不会静默变成成功。
候选保存真实 token 用量，但仍需显式 approve；过时版本继续拒绝。
当前 logical small/reasoning 两路使用同一个配置模型，不是已完成的多模型 routing。

## 流式调用和失败语义

- 使用 Responses API、`store=False`、`reasoning.effort=none`，默认最多 256 输出 token。
- SDK 自动重试关闭，连接超时 5s、读取超时 10s；默认协作 deadline 30s。
  deadline 在事件边界检查，不能抢占阻塞中的网络 read。网络 read 超时也是有限的，
  但不等于整个调用严格在 30s 内返回；消费者处理 chunk 的时间也计入 wall deadline。
- 只在 `response.completed` 后成功；截断、拒绝、失败、无终止事件均失败。
- 取消后拒收后续片段，关闭 stream；协调器异常退出也显式关闭生成器。
  取消不能撤销供应商已发生的计算或收费。
- `model_calls` 记录请求 ID、输入 hash、模型、状态、response ID、首个文本 delta
  耗时、总耗时和供应商报告的 token 用量；不保存密钥、源文本或原始错误 body。
- started 后崩溃会留下未知状态，重复流式 call ID 拒绝自动重放，需要对账。
  记忆任务重试使用新的模型 call ID，可能重复付费；不宣称外部 exactly-once。
- 流被提前关闭或连接丢失时，最终 usage 可能拿不到。未知用量不能记作零成本；
  结果单独报告 `calls_without_final_usage`。token 数不等于已核对发票费用。
- 原有 session 阶段预算仍是声明单位，和新 token 账本分开，不混充美元预算。

## 真实实验

命令会产生真实 API 用量，输入全部是仓库里的合成 fixture；不自动读取私人文档。
每个场景只跑一例，没有调参反复挑结果。问题使用最多 128 输出 token，提取最多 1024。

```sh
export PYTHONPATH=src
.venv/bin/python scripts/build_runtime.py
export VOICE_RUNTIME_LIBRARY="$PWD/build/libvoice_runtime.so"
# SQLite：
.venv/bin/python experiments/live_text.py
# 已启动独立本地基础设施时，使用环境中的测试 DSN/Redis：
.venv/bin/python experiments/live_text.py --postgres
```

实际覆盖：

1. worker 尚未提取，最终发言已进入模型上下文。
2. 子分支采用 CEDAR，父分支仍保持 RAVEN。
3. 关闭并重新打开 Pipeline 后恢复 RAVEN。
4. 两次显式记忆修订后使用 MAPLE，覆盖历史提及。
5. 明确 PostgreSQL 决定与 Redis 试探性建议分开。
6. 没有决定时不提取 Kafka 候选。
7. 真实 LLM 输出经过 C++ 分句、合成 TTS 字节和软件 render。

这些展开为 8 个调用场景。初轮与最终结果分别保留在
`experiments/live-text-results-initial.json` 和 `experiments/live-text-results.json`，
包含回答、检查条件、原始 token/耗时和源码 hash。

这只是小规模集成验证：substring 检查不是独立语义评分，8/8 不能证明普遍准确率、
抗提示注入能力、routing 收益、实际首段语音延迟或生产 SLA。
CI 使用合成 HTTP SSE、mock 与真实本地基础设施，不配置密钥、不执行付费模型调用。

实现依据：[Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses)、
[Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)。
