# PostgreSQL / Kafka / Redis：本地运行与恢复

本轮加入三个真实服务的适配器，SQLite 仍是无依赖参考模式。没有接入在线 LLM、
真实 STT/TTS、设备或多租户部署；模型费用不在本轮测量范围。

## 数据流

```mermaid
flowchart LR
  U[最终发言] --> P[(PostgreSQL 发言 + outbox)]
  P --> C[立即组装上下文]
  C <--> R[(Redis 派生缓存)]
  P --> O[独立 outbox relay]
  O --> K[Kafka ID 事件]
  K --> W[worker durable intake]
  W --> Q[(PostgreSQL leased tasks)]
  Q --> E[规则或已配置提取器]
  E --> A[候选；显式确认]
  A --> V[版本检查与记忆更新]
  V --> P
```

实时路径在提交 PostgreSQL 后即可读取最终发言，不等待 relay、Kafka、worker 或摘要。
Kafka 事件只包含版本和 task ID；worker 从数据库读取权威 payload。每个部署必须
使用自己的数据库和 topic/group，不能把多个独立 workspace 数据库混入同一默认 topic。
当前数据库对应一个 workspace。

## 启动

需要 Docker Compose、Python 3.11+；C++ 会话示例额外需要 C++17 编译器。
下面的凭据仅是 Compose 本地开发值，端口只绑定 127.0.0.1。

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[infra]'
docker compose up -d
export VOICE_DATABASE_URL='postgresql://voice:local-dev-only@localhost:55432/voice'
export VOICE_REDIS_URL='redis://127.0.0.1:56379/0'
export VOICE_KAFKA_BOOTSTRAP='127.0.0.1:59092'
export PYTHONPATH=src
.venv/bin/python -m voice_context.broker init-topic
```

分别在两个终端启动后台进程：

```sh
.venv/bin/python -m voice_context.broker relay
.venv/bin/python -m voice_context.broker worker
```

第三个终端启动 JSONL gateway，输入以下动作：

```sh
.venv/bin/python -m voice_context.gateway --async-dispatch
```

```json
{"action":"submit","transcript_id":"turn-1","branch":"main","session":"s","text":"remember storage: PostgreSQL"}
{"action":"context","branch":"main"}
{"action":"status","task_id":"transcript:turn-1"}
{"action":"approve","task_id":"transcript:turn-1","keys":["storage"]}
```

`status` 在 Kafka intake 完成前会返回 KeyError；候选成功后才能 approve。
默认仍使用规则提取，`--model` 可选 Ollama；尚未做本轮真实模型实验。
交互界面尚未实现，这是可复用基础设施接口。

Python API 使用 `Pipeline(dsn, publish_on_submit=False, redis_url=url)`。
C++ 协调器同样支持 `Conversation(dsn, session, publish_on_submit=False, redis_url=url)`。
**基础设施模式必须关闭 submit 的本地发布。** 默认 SQLite 兼容路径继续使用本地队列。
`work` 是本地参考模式动作，会直接投递 outbox，Kafka 部署应使用独立 worker。
`--cascade` 的审计库仍仅支持 SQLite，PostgreSQL CLI 会明确拒绝该组合。

## 故障语义

- 最终发言、可见性引用、提取时的预期记忆版本与 outbox 同事务写入。
- relay 收到 broker delivery ack 后才标记 published。ack 后、数据库标记前崩溃会
  重复发布；多个 relay 也可能重复发布，数据库任务 ID 负责去重。
- Kafka intake 在持久化 leased task 后才同步提交 offset。提取可稍后完成；
  offset 成功不表示模型提取完成。崩溃后未提交记录重放，已入库任务不重复创建。
- worker 租约过期可以重新领取，旧租约不能完成任务；有限次数失败进入数据库
  `dead` 状态。外部模型调用可能重复，需供应商幂等键；不承诺外部 exactly-once。
- 重复确认不重复写记忆；过时结果按 expected version 拒绝。
- relay/worker 常驻模式在连接失败后关闭连接、重新建立 pipeline 并重试。
  `--once` 失败直接退出，便于进程管理器检测。默认无效消息不提交 offset；
  可选 `--quarantine-invalid` 将确定损坏的 envelope 持久隔离后继续消费，详见下文。
- Redis key 含数据库 namespace、全局 revision、branch/query/budget。所有影响
  上下文的表由 PostgreSQL trigger 更新 revision，旧 key 自然不可达并按 TTL 过期。
  其他 Pipeline 进程的写入同样使旧缓存失效；自定义 tokenizer 绕过缓存。
- Redis 连接/读取超时设为 50ms，失败直接查 PostgreSQL；丢缓存不丢记忆。
  每次命中仍读取 PostgreSQL revision，不是零数据库读的缓存。
- PostgreSQL 重启会中断在途连接，当前调用可能失败；调用方用相同 ID 重试。
  后台进程自动重连。Redis 不承担数据库故障期间的权威读。

## 当前取舍

PostgreSQL adapter 仅适配仓库固定 SQL，不是通用 ORM。事务使用数据库级 advisory
锁保持 SQLite 的串行写语义，所有应用写入必须经 adapter；缓存组装也在该锁范围。
这是正确性基线，**尚未实现多 workspace 隔离或高吞吐分片锁**。
连接建立超时 5s，数据库 lock timeout 5s、statement timeout 10s；超时会失败而不是无限等待。持续写入会降低
全局缓存命中率；Redis 查询目前也会延长事务持锁时间，需要后续并发实测再优化。

启动时执行幂等建表及列检查，目前没有版本化升级工具，也没有 SQLite 数据自动
迁移到 PostgreSQL。现有 SQLite 文件保持原样；新部署建立独立 PostgreSQL 状态。
Kafka 是单节点、单副本 KRaft，Compose 使用本地明文网络，不构成生产 HA。
PostgreSQL 和 Kafka 使用持久卷，Redis 可丢弃。

## 复现实验

```sh
export VOICE_TEST_POSTGRES="$VOICE_DATABASE_URL"
export VOICE_TEST_KAFKA="$VOICE_KAFKA_BOOTSTRAP"
export VOICE_TEST_REDIS="$VOICE_REDIS_URL"
.venv/bin/python scripts/wait_infra.py
.venv/bin/python scripts/build_runtime.py
export VOICE_RUNTIME_LIBRARY="$PWD/build/libvoice_runtime.so"
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python experiments/infrastructure.py --restart-services
```

`--restart-services` 实际停止本项目 Redis、重启 PostgreSQL/Kafka，只在独立本地
Compose 栈运行。不带该参数保留服务，仍运行 broker 不可用、重复、租约、乱序、缓存检查。
测试各自创建独立 schema/topic 并清理；不执行 Redis FLUSHALL。
CI 的 infrastructure job 运行真实服务、全量测试与重启实验。

本机最终结果：81 项测试全部通过；14 项故障/恢复检查全部通过。微型上下文
30 次读取中，PostgreSQL p50/p95 为 2.37/3.37ms，Redis 路径为 1.26/1.47ms；
这是两条完整读取路径的本机对照，不单独归因到 Redis 算法或网络优化。

原始结果见 `experiments/infrastructure-results.json`，包含源码 hash、客户端版本、
14 项正确性检查与上下文读取各 30 个样本。微型数据集、单机单副本和串行负载的
p50/p95 不能作为生产 SLA、语音延迟或规模化吞吐结论。

实现依据：[Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)、
[Kafka producer acknowledgements](https://kafka.apache.org/27/configuration/producer-configs/)、
[Redis cache-aside](https://redis.io/docs/latest/develop/use-cases/cache-aside/)。


## 可选的坏消息隔离（本地 infra 版本）

```sh
PYTHONPATH=src .venv/bin/python -m voice_context.broker worker --quarantine-invalid
PYTHONPATH=src .venv/bin/python -m voice_context.broker quarantine-status
```

使用上面的 `VOICE_DATABASE_URL` / `VOICE_KAFKA_BOOTSTRAP` 配置。此选项只改变独立
Kafka worker，不会自动开启网页版的 Kafka 路径，也不需要真实语音或付费模型。

- 默认保持严格重试。显式开启后，坏 JSON、空消息、超大消息（16 KiB 上限）、
  错误形状、空 task ID 和 key 不匹配写入数据库 `kafka_quarantine`。
- 隔离事务提交之后才同步提交 Kafka offset。任何数据库/提交错误继续抛出，由
  worker 关闭 consumer 后重连；数据库失败时绝不跳过消息。
- 已隔离但未提交 offset 的消息会重放。来源身份与 topic/partition/offset 的摘要
  唯一键使隔离幂等。来源身份包括 bootstrap 字符串与消费组；部署需保持它们稳定。
  同名 topic 删除重建或 broker 地址重用时应更换消费组，避免来源位置复用。
- 未知协议版本、未知 outbox 引用、队列写入失败依然阻塞并重试：它们可能是版本
  滚动升级、配置错误或暂时的状态问题，不能当坏消息丢弃。
- 表只保存来源位置、固定错误码、payload SHA-256 和时间，不复制原始内容或 key。
  它是隔离审计表，不是带完整原文的 Kafka DLQ。原文可在 Kafka retention 期限内
  按位置调查；不会自动重放。修复后应从权威 outbox 发布正确的 ID 事件。
- `quarantine-status` 显示数量和错误分类；隔离记录暂无自动保留期/清理任务。

### 可复现故障实验

```sh
VOICE_TEST_KAFKA=127.0.0.1:59092 \
VOICE_TEST_POSTGRES=postgresql://voice:local-dev-only@127.0.0.1:55432/voice \
.venv/bin/python experiments/kafka_recovery.py
```

实验创建并清理独立 PostgreSQL schema 和单分区 topic，不重启共享服务、不清理用户
数据。固定场景为一条坏消息后接一条正常事件；先验证默认模式连续三次重连仍阻塞，
再注入隔离持久化后、offset 提交前的崩溃，验证重放只产生一条隔离记录，且后续正常
提取任务完成。结果保存到 `experiments/kafka-recovery-results.json`。恢复时间包含
消费组重新分配，仅是本机正确性场景记录，不代表生产 SLA 或吞吐优化。
