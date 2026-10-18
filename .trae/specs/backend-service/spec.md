# 后端服务（backend-service）- 需求规格

## Overview
- **Summary**：在仓库根新建 `backend_service/` 服务（Python 3.12 + FastAPI + uvicorn 单 worker），落地 `docs/SDD-后端.md` v0.2 的全部内容：五层结构（api / application / algorithm / data / storage）、问数 SSE 协议、会话与消息、报表沉淀与刷新、双 schema 双角色双引擎、QueryRunner 执行兜底、L0 真实抽取与 pgvector Repository 的后端实现、db/api 容器化。
- **Purpose**：P5 三轮 `/spec` 的第二步。后端是算法内核的唯一宿主与依赖注入方，也是前端唯一对话方；本步把 `run_chain` 以进程内函数方式接入并包上 HTTP/SSE、持久化与部署，不重做算法内部步骤。
- **Target Users**：前端 web 容器（下一 `/spec` 轮次，同源 `/api/v1` 消费方）、演示用户（浏览器经 web 反代访问；本步可直接对 api 做接口验收）。

## Goals
- 完整实现 SDD §3 接口契约：`POST /chat/turns`（新问/澄清确认/recalibrate 三选一）、`GET /chat/turns/{id}/events`（SSE）、`cancel`、sessions 三个、reports 八个、`/health`。
- application 层调 `run_chain` 并注入全部依赖；节点回调按 SDD §3.2 写死映射为三 stage；终态六 action 映射为五终态帧（answer/clarification/rejection/error/cancelled）+ done。
- 镜像 ChainResult：所有出前端报文的 DTO 只从算法 `ChainResult` 派生（insight、chart 五型可 null、comparison.changes、六 reason_code），不另发明字段。
- 存储：app schema 五表（sessions/messages/reports/exemplar/meta_schema_cache）SQLAlchemy `create_all` 幂等建表；reports 快照打开直读、刷新带 QuerySpec 从 S5 重跑；SQL/trace 只落 `internal` 不向前端输出。
- 执行安全：QueryRunner（psycopg 裸连接、单条 SELECT、`statement_timeout=10s`、行限幅回传 truncated）；chatbi_ro 物理只读；app_user 仅 app schema DML。
- 真实实现算法侧留给后端的两个 Provider：经 information_schema/pg_catalog 的 L0 SchemaProvider、psycopg+pgvector 的 Repository；Embedding 缺失时 exemplar 不建表/不启用。
- 容器：`backend_service/db/*.sql`（角色+schema+vector 扩展）、api 镜像（python:3.12-slim）、docker compose 的 db/api 两服务本步可起、`/health` 可验。

## Non-Goals
- **不重做算法内部任何步骤**：不实现 8 步节点、不写 SQL builder/lint、不改 ChainResult；算法包以仓库根 `algorithm/` 目录原样依赖（按 algorithm-chain 轮次交付）。
- **不做任何前端页面/前端构建**：不建 `web/` 工程；compose 的 web 服务与 nginx 配置归前端轮次（已拍板）。
- **不产 dw 六表 DDL 与业务 seed**：数仓表与大促数据是 P6（metrics-dictionary §5）；本步 init SQL 只到角色/schema/扩展，集成测试用测试夹具 DDL。
- 不做登录/账号/多租户/RBAC（owner_id 固定 `'default'` 字段预留）；不做 Supabase 对接代码（仅 Repository 接口可换的形态约束）；不做 K8s/CI、消息队列、多 worker、外部 checkpointer/事件存储。
- 不修改 `docs/` 任何文件；不创建 `backend_service/`、`algorithm/`（消费）、`.trae/specs/` 之外的目录。

## Background & Context
- 权威输入：`docs/SDD-后端.md` v0.2；链路与契约冲突以 `docs/SDD-算法应用.md` v0.4 为准；功能必要性以 `docs/PRD.md` F1~F9 为度；总览只当地图。
- 上游依赖（algorithm-chain 轮次产物，本步消费不重写）：`run_chain` 入口、`ChainResult/ChainState` 强类型、`QueryRunner/LLMClient/EmbeddingClient/SchemaProvider/Repository` 协议、资源加载器、内存 checkpointer。
- 仓库现状：`algorithm/` 包已由 algorithm-chain 轮次交付（Task 1~15，pytest 46 用例全绿，含 S5 刷新/S4 recalibrate 两中段入口与 ChainResult service-only 字段），本步无前置阻塞。

## Functional Requirements

### 服务骨架与横切
- **FR-1**：FastAPI 应用工厂 + `/api/v1` base path；统一错误信封 `{error:{code,message,retryable}}` 与 §8 错误码→HTTP 映射（E_VALIDATION 400、E_TURN_NOT_FOUND/E_NOT_FOUND 404、E_NAME_CONFLICT/E_CLARIFY_EXPIRED/E_REPORT_NOT_SAVEABLE 409、E_LLM_UNAVAILABLE 同步 502/SSE error、E_INTERNAL 500）；时间 ISO-8601、id UUID 字符串；仅本地开发态开 CORS（同源经 nginx 是正式形态）。
- **FR-2**：`config.py` 读 SDD §7.3 全部 env（LLM_*、EMB_*、双 DATABASE_URL、QUERY_TIMEOUT_SECONDS=10、ROW_LIMIT_DEFAULT=500、ROW_LIMIT_MAX=1000、RESOURCES_PATH），缺失值给默认；问题长度上限 `QUESTION_MAX_LENGTH=500`（空/超长 400；与 SDD-前端 §3.1 客户端预校验统一为 500，三方对齐）。

### 问数编排（F1/F2/F3/F4）
- **FR-3**：`conversation_service` 是唯一调 `run_chain` 的地方（api 层不得直接调）；负责：建 turn（uuid+running）、按算法实际签名组参（主入口 `question` 或澄清重入 `clarified_question+clarify_id` / recalibrate 与刷新中段入口三态之一 + `conversation_summary` 取最近 5 轮 answer 口径 + `thread_id`/checkpointer）、组装算法 `Deps`（settings、llm、schema_provider、query_runner、embedding?、repository?、resources 预加载对象、on_event）、传事件回调。
- **FR-4**：三入参互斥校验（恰好一种，否则 400）；②clarify 校验票据存在且 pending（否则 409 E_CLARIFY_EXPIRED），按 selection.type（option/time_preset/custom）拼 clarified_question；③recalibrate 取 source turn 已落库 QuerySpec 从 S4 入参强制出 clarify（不执行 SQL），source 不存在 404；POST 成功返 202 `{turn_id,session_id,status:running}`。
- **FR-5**：SSE 流帧顺序 = 零或多个 stage → 恰好一个终态帧 → done；算法 `on_event` 回调（`node_started`/`node_finished` 载荷 `{"node":"S1".."S8"}`）按写死映射翻 stage：S1=understanding（正在理解问题），S2/S3/S4=checking_caliber（正在核对口径），S5/S6/S7/S8=querying（正在取数），同 stage 去重；建流 404 E_TURN_NOT_FOUND；进程内事件缓冲保留 10 分钟，支持 `Last-Event-ID` 尽力补帧。
- **FR-6**：终态映射：answer→`answer` 帧（含空结果 rows=[]/chart=null）；clarify→`clarification` 帧（镜像载荷 + status:pending）；not_answerable/query_gen_failed/query_failed→`rejection` 帧（六 reason_code 原样，QUERY_TIMEOUT/QUERY_ERROR 标可重试语义）；action=error→`error` 帧；取消→`cancelled` 帧；每帧后恒收尾 `done`。
- **FR-7**：AnswerEvent 逐字段镜像 ChainResult.answer + 后端信封：`table/chart/insight/caliber/comparison` 五字段不增删业务字段；派生 `data_time_range`（取 QuerySpec.time_range）、`queried_at`、`saveable = action=answer 且 rows 非空`；空结果同构 answer 且 saveable=false。
- **FR-8**：取消：POST `cancel` 返 202 cancelling；进程内 turn 取消注册表 + 算法协作点（节点间标志、S6 执行期经连接 cancel/statement_timeout 兜底）；流上到 cancelled 帧并落一条 note 消息（kind=cancelled）。
- **FR-9**：落库时机：建 turn 落 user 消息（会话内 seq 递增）；终态落一条终态消息（clarification/answer/rejection/note），payload 为对应终态切片；`internal` 列存 `{sql, trace, query_spec}`（三键取自 `ChainResult.sql / ChainResult.trace / ChainResult.query_spec`——service-only 契约字段，见接缝节第 6 点；sql=S5 生成 S6 实际执行，lint 未过/未执行时为最后生成 SQL 或 null；query_spec 供 recalibrate 与报表刷新，三键已拍板）；stage 过程事件永不落库；任何出前端的报文（含 SSE 与会话还原）不含 sql/trace/query_spec。
- **FR-10**：多轮口径摘要：会话还原与新 turn 时从最近 5 条 answer 消息的 caliber.detail 构造 session_caliber_summary；澄清重入携带同 thread/checkpointer（进程内内存）。

### 会话（F7）
- **FR-11**：GET `/sessions?offset&limit`（按 last_question_at 倒序，默认 0/50）出 `{id,title,message_count,last_question_at,created_at}`，title=首问原文；GET `/sessions/{id}/messages` 按 seq 完整还原子句（user/clarification 含最终 status/answer/rejection/note）；DELETE 级联删消息返 204；不存在 404。

### 报表（F5/F6）
- **FR-12**：POST `/reports`：只收 `{turn_id,title,overwrite}`；服务端按 turn_id 找已落库 answer 载荷（不信任前端自报内容）；非 answer 或 rows 空 → 409 E_REPORT_NOT_SAVEABLE；同名 `unique(owner_id,title)` 冲突 → 409 E_NAME_CONFLICT + existing；overwrite=true 同事务更新快照/caliber/query_spec/sql/data_time_range，id 不变；新存 201 `{id,title,created_at}`；写库单事务，字段缺失整体回滚。
- **FR-13**：GET `/reports?q=&offset=&limit=` 名称包含匹配、按创建时间倒序，出列表项；GET `/reports/{id}` **直读 snapshot/caliber，不调 run_chain、不连 analytics、不出 LLM**；PUT 改名（空名 400、同名 409）；DELETE 204。
- **FR-14**：POST `/reports/{id}/refresh`：取存的 query_spec 调算法**刷新入口从 S5 开始**（gen_sql→lint→execute→build_view→insight），不重走 S1~S4、不重新澄清；同步返终态同构体（answer 切片含新 queried_at；或 query_gen_failed/query_failed rejection 切片；0 行空 answer）；**不落新消息、不改写报表快照**。
- **FR-15**：POST `/reports/{id}/continue-session`：新建会话，`inherited_spec=报表 query_spec`、title=报表原问题，不插假消息，返 `{session_id}`；继承口径到达算法的唯一通道是 `conversation_summary`（run_chain 无 inherited_spec 参数）——该会话**首问**时后端把 inherited_spec 的口径摘要（caliber_summary/时间/对比段序列化文本）拼入 `conversation_summary`，S1 prompts 消费它（承接"那个渠道"类指代）。

### 健康检查与启动生命周期
- **FR-16**：GET `/health` 出 `{status, checks:{db,llm,embedding}}`：db=ok/error；llm=ok/unconfigured(无 key)/error；embedding=ok/unconfigured/error（unconfigured 不拖垮整体；llm unconfigured|error 或任一 error → degraded）。
- **FR-17**：api 启动序列：配置校验 → app 引擎 `create_all`（幂等）→ 经 analytics 连接跑 L0 抽取并进程内缓存（可选 meta_schema_cache）→ 仅 EMB_* 齐全时 ensure exemplar 表与 hnsw（维度按 EMB_DIM 校验）；任一可选增强缺失不阻断启动；LLM 无 key 不阻断启动。

### 数据层
- **FR-18**：双引擎（data/engines.py）：APP 引擎 SQLAlchemy2（仅 app schema DML）；analytics 引擎 psycopg3 裸连接（`search_path=dw`、`statement_timeout=10s`、只读连接串）；写操作只可能走 APP 引擎。
- **FR-19**：QueryRunner 实现算法协议：执行前执行层兜底（单条 SELECT、拒绝多语句/写操作）、运行时 `statement_timeout=10s`、取 ROW_LIMIT_MAX+1 行判截断并回传 `truncated`（默认限幅 500 由算法 LIMIT 注入，执行层硬顶 1000）；超时→QUERY_TIMEOUT、异常→QUERY_ERROR 的错误归一在算法 execute 节点协议语义内，Runner 抛对应异常类型；Runner 不解析/不改写业务 SQL。
- **FR-20**：真实 L0 SchemaProvider：经 chatbi_ro 读 information_schema+pg_catalog，产出表/列/类型/主外键/中文注释/枚举采样 SchemaBlock（算法 retrieval 定义的形状）；支持进程内缓存复用。
- **FR-21**：PgRepository 实现算法 Repository 协议三方法：`search_exemplars`（embedding/keywords 双通道 topN，hnsw 余弦，维度 EMB_DIM 校验）、`upsert_exemplar`、`load_schema_cache`；meta_schema_cache 的**写入由后端启动序列自行落库**（协议只含 load，算法只读缓存）；问数链路对 exemplar 只读；EMB 未配置时不实例化、S3 由算法侧降级 lexical。

### 部署
- **FR-22**：`backend_service/db/01-init.sql`：建 app/dw schema、app_user（schema app 全部 DML）与 chatbi_ro（schema dw SELECT + information_schema/pg_catalog 只读，无建表/写权限）、`CREATE EXTENSION vector`；幂等（IF NOT EXISTS/DO 守卫）；**不含 dw 业务表 DDL/seed（P6）**。
- **FR-23**：`backend_service/Dockerfile`（python:3.12-slim 单阶段）同时装入 `backend_service/` 与 `algorithm/`（构建上下文为仓库根），装 requirements，uvicorn 单 worker 起 8000；`.env.example` 提交、真实 `.env` 不提交；docker compose 本步交付 db（pgvector/pgvector:pg16，pg_isready、pgdata 卷、挂 init SQL）与 api（depends_on healthy）两服务；**本步不含 web 块（已拍板）**，web 服务与 nginx 配置由前端轮次补齐并首次达成三服务 F9。

## Non-Functional Requirements
- **NFR-1（分层纪律）**：层间依赖只向下；静态检查保证：api 层不 import run_chain、algorithm 层不 import storage/不出现连接串、analytics 引擎无写 API、storage 不感知 ChainResult 之外的业务判断。
- **NFR-2（可测性）**：测试分两级——① **离线单测**（无 DB/无 key/无网络）：用同签名假 run_chain、内存仓储/注册表、FakeQueryRunner 跑路由/SSE/服务规则，必须全绿；② **集成测试**（需本地 db 容器）：标记 integration，覆盖真实 PG 的权限/超时/截断/L0 抽取/pgvector/create_all 幂等，验收时人工 `docker compose up db` 后跑一次并留输出作为本步 Done（已拍板）。
- **NFR-3（安全）**：所有面向用户文案业务化中文；SQL/堆栈/trace/技术细节不出报文；只读角色物理不可写（集成测试实证）。
- **NFR-4（单进程假设）**：turn 注册表、事件缓冲（10min）、checkpointer 进程内存；代码不假设多 worker；重启后在跑 turn 不可恢复（已落库的终态消息不受影响）。
- **NFR-5（幂等与可重置）**：create_all 与 init SQL 重复执行无副作用；`docker compose down -v && up` 可干净重置。

## Constraints
- **Technical**：FastAPI、uvicorn 单 worker、SQLAlchemy 2（app only）、psycopg3 裸连接（dw）、pydantic v2、sse-starlette 或等价 SSE 响应；Python 3.12；db 镜像固定 `pgvector/pgvector:pg16`。
- **Business**：单用户 owner_id='default'；可答边界＝已接入 dw 库（L0），不提供绕过链路直查物理表入口。
- **Dependencies**：强依赖 algorithm-chain 轮次的包与三处入口接缝——见下节；前端不存在，接口用 TestClient 与 curl 级验收。

### 上游算法接缝（以已交付的 `algorithm/` 实现为准，后端只消费不重写）
1. **主入口（已交付）**：`run_chain(*, question="", clarified_question=None, clarify_id=None, query_spec=None, start_at=None, deps, thread_id=None, on_event=None, checkpointer=None, conversation_summary="") -> ChainResult`——扁平关键字参数，无 ChainEntry 包装；澄清重入传 `clarified_question+clarify_id` 并复用同 `thread_id`（checkpointer 恢复槽位与轮次）；
2. **依赖容器（已交付）**：`Deps{settings, llm, schema_provider, query_runner, embedding=None, repository=None, resources, on_event}`——`resources` 为经算法 loader 以 `RESOURCES_PATH` 预加载的 `Resources` 对象（后端不传路径串）；LLM 未配 key 时客户端照常构造、调用期抛 `LLMUnavailableError` → `E_LLM_UNAVAILABLE`；
3. **事件回调（已交付）**：`on_event(event, payload)`，`node_started/node_finished` 载荷 `{"node":"S1".."S8"}`，`terminal` 载荷 `{"action":...}`；
4. **协议形状（已交付）**：QueryRunner `run(sql) -> QueryResult`；Repository `search_exemplars(embedding=?, keywords=?, top_k) / upsert_exemplar / load_schema_cache`；SchemaProvider `all_blocks() / enum_candidates(term)`；
5. **两个中段入口（已交付，pytest 46 用例全绿）**：`start_at="S5"` 刷新入口（接受 `query_spec` 从 S5 起跑，FR-14 用）、`start_at="S4"` recalibrate 入口（接受 `query_spec` 从 S4 进入并强制产出 clarify 卡，FR-4③ 用）；
6. **service-only 契约字段（已交付，algorithm-chain spec OQ-4 / SDD-算法应用 §6）**：`ChainResult.query_spec`（本次对齐产出的 QuerySpec）与 `ChainResult.sql`（S5 生成、S6 执行的 SQL）——FR-9 internal 三键、FR-12 报表保存、FR-4③ recalibrate 的唯一数据来源；只落库，禁止出现在任何前端报文（B11 白名单扫描覆盖）。

> **实现顺序约束（已满足）**：algorithm-chain 增补轮次（两入口 + service-only 字段）已先行交付并测试全绿（pytest 46 用例），后端编码无前置阻塞。

## Assumptions
- 服务源码根 `backend_service/`，测试在 `backend_service/tests/`；集成测试夹具 DDL（仿 metrics-dictionary 六表的最小 dw 表 + 中文注释/枚举）放 `backend_service/tests/fixtures/`，仅测试用，不进 init SQL。
- turn 不建表：运行态在内存注册表；turn 与消息的关联靠消息落库时写入的 turn_id（AnswerEvent 信封自带 turn_id；answer 消息以 payload.turn_id 反查），报表保存据此找源 answer。
- 列表分页默认 offset=0/limit=50，limit 上限 200。
- SSE 缓冲 10 分钟为尽力补帧，不承诺断线期间所有历史可回放；超时引导重问（SDD §3.2）。
- 前端轮次交付 web 后，浏览器入口 http://localhost:8080；本步 api 直连验收（容器内 8000 或本机映射）。

## Acceptance Criteria

### AC-1: 应用骨架与错误信封
- **Type**: `rule`
- **Given**: 启动 app（不连真实 db 时路由仍可装配）
- **When**: 请求一个不存在资源 / 提交空问题
- **Then**: 返回统一信封与正确 code/HTTP（404 E_NOT_FOUND 或 400 E_VALIDATION）；时间/UUID 格式符合约定
- **Pass Condition**: TestClient 单测覆盖 §8 全部 code 的触发路径
- **Evidence**: backend_service/tests 单测输出

### AC-2: 建 turn 三态互斥与同步错误
- **Type**: `rule`
- **Given**: conversation 接口
- **When**: ① 正常新问；② 同时传两种入参；③ 空/超长问题；④ 不存在或已确认的 clarify 票据；⑤ recalibrate 不存在 turn
- **Then**: ① 202 running；② 400；③ 400；④ 409 E_CLARIFY_EXPIRED；⑤ 404 E_NOT_FOUND
- **Pass Condition**: 五条各有单测（假 run_chain，不进真实链路）
- **Evidence**: chat 路由测试

### AC-3: SSE stage 映射与帧序
- **Type**: `rule`
- **Given**: 脚本化 on_event 回调依次发 node_started/node_finished（载荷 {"node":"S1".."S8"}）
- **When**: 消费 events 流
- **Then**: 收到 understanding/checking_caliber/querying 三个（同段去重）→ 恰一终态帧 → done；各 action 的终态帧名符合 FR-6 映射表
- **Pass Condition**: 六 action 各一脚本断言帧序/帧名；Last-Event-ID 补帧用例存在
- **Evidence**: SSE 测试输出

### AC-4: 报文逐字段镜像 ChainResult
- **Type**: `rule`
- **Given**: 算法返回的各型 ChainResult（answer 含对比/空结果、clarify、三 rejection、error）
- **When**: 经服务层转 SSE/会话/报表报文
- **Then**: 字段名/可空性/枚举与算法 §6 一致（insight、chart null、trend_line 等五型、changes[].rate_delta null、六 reason_code）；后端仅多 turn_id/session_id/question/data_time_range/queried_at/saveable/status 信封字段
- **Pass Condition**: 有逐字段快照对照测试；grep 不到 narrative/dual_line 残留
- **Evidence**: mapper 单测

### AC-5: saveable 与空结果
- **Type**: `rule`
- **Given**: rows 非空 answer / rows=[] answer
- **When**: 出帧
- **Then**: 非空 saveable=true；空结果同构 answer、chart=null、saveable=false，且无独立 empty 码
- **Evidence**: 单测

### AC-6: 澄清确认前不出数与票据流转
- **Type**: `rule`
- **Given**: 首轮 clarify 终态
- **When**: 在用户确认前检查；再以 option/time_preset/custom 三种 selection 确认
- **Then**: 首轮 FakeQueryRunner 零调用且已落 pending clarification 消息；确认时拼出 clarified_question 并以 S1 重入；确认/取消后票据状态终态化，重复确认 409
- **Pass Condition**: 单测断言调用计数、消息 status、重入入参
- **Evidence**: conversation_service 测试

### AC-7: 落库内容与内部字段不外泄
- **Type**: `rule`
- **Given**: 一轮完整 answer（含 sql/trace/query_spec）
- **When**: 检查 messages 行与所有出接口报文
- **Then**: internal 含 sql/trace/query_spec；SSE 帧、会话还原、列表、报表打开报文均不含这三键；stage 事件无落库
- **Evidence**: 仓储+序列化白名单单测

### AC-8: 会话列表/还原/删除
- **Type**: `rule`
- **Given**: 多会话多消息（含各 type）
- **When**: 列表、还原、删除
- **Then**: 排序/分页/title/message_count 正确；还原按 seq 且含澄清最终 status；删除级联；404 路径正确
- **Evidence**: sessions 路由+仓储单测

### AC-9: 报表保存门槛与同名事务
- **Type**: `rule`
- **Given**: 可存 answer / 空结果 / rejection turn；同名报表
- **When**: POST /reports（含 overwrite 两态）
- **Then**: 门槛 409 E_REPORT_NOT_SAVEABLE；同名 409+existing；覆盖成功且 id 不变、快照字段整包更新；新存 201；字段缺失触发回滚（无半成品）
- **Evidence**: report_service 单测

### AC-10: 报表打开只读快照
- **Type**: `rule`
- **Given**: 已存报表
- **When**: GET /reports/{id}
- **Then**: 服务层不调用 run_chain、不创建 analytics 连接（用 spy 断言调用计数=0）；响应 snapshot/caliber 与保存时一致
- **Evidence**: 单测 spy 输出

### AC-11: 刷新从 S5 且不产生副作用
- **Type**: `rule`
- **Given**: 已存报表 + 脚本化算法刷新入口（成功/超轮/超时/0 行）
- **When**: POST refresh
- **Then**: 调用的是算法 S5 刷新入口（断言未走 S1 主入口）；同步返回对应终态同构体；messages 无新增、reports 快照与 updated_at 不变
- **Evidence**: 单测

### AC-12: continue-session 继承口径
- **Type**: `rule`
- **When**: POST continue-session 后在新会话发首问
- **Then**: 新会话 inherited_spec=报表 query_spec、无假消息；新会话首问的 `conversation_summary` 含继承口径文本（来自 inherited_spec）；报表本身不变
- **Evidence**: 单测

### AC-13: 双引擎与只读安全（集成）
- **Type**: `rule`
- **Given**: db 容器 + init SQL
- **When**: app_user 写 app 表；chatbi_ro 尝试写 dw/建表/读 app；create_all 重复执行
- **Then**: app_user DML 成功；ro 全部被 PG 拒绝；create_all 二次执行无报错无重复
- **Pass Condition**: integration 标记测试在 db 容器上全绿
- **Evidence**: pytest integration 输出

### AC-14: QueryRunner 超时/限幅/单语句（集成）
- **Type**: `rule`
- **Given**: analytics 引擎
- **When**: 执行 pg_sleep(12)、返回 >1000 行的查询、多语句/写操作字符串、正常 SELECT
- **Then**: 超时归一为 QUERY_TIMEOUT 类异常；截断置 truncated=true 且最多取 1000+1 判定；多语句/写在执行前拒绝；正常返回列/行结构
- **Evidence**: integration 测试

### AC-15: L0 真实抽取（集成）
- **Type**: `rule`
- **Given**: 测试夹具 DDL（六表 + 中文注释 + 美妆多候选枚举）
- **When**: 启动期 SchemaProvider 抽取
- **Then**: 得到六表 SchemaBlock；列注释/类型/主外键齐；枚举采样含美妆四个候选与档期四值
- **Evidence**: integration 测试

### AC-16: exemplar pgvector 条件启用（集成）
- **Type**: `rule`
- **Given**: ① 未配 EMB_*；② 配置 EMB_DIM
- **When**: api 启动；upsert+search exemplar
- **Then**: ① 不建 exemplar/不索引、服务正常；② 建表+hnsw、写入与 topN 相似度检索一致，维度不符报错不落半截
- **Evidence**: integration 测试

### AC-17: 健康检查与无 key 启动
- **Type**: `rule`
- **Given**: db 正常；LLM/EMB 分别 unconfigured/ok/error
- **When**: GET /health；无 LLM key 启动后提问
- **Then**: status/checks 符合 FR-16 聚合规则；无 key 启动成功，提问链路在 SSE error 帧得 E_LLM_UNAVAILABLE(retryable=true)
- **Evidence**: 单测+集成

### AC-18: 容器与 compose
- **Type**: `rule`
- **Given**: Docker 环境
- **When**: `docker compose config` 校验后 `up -d db api`
- **Then**: db healthy 后 api 启动无错（create_all/L0 抽取跑完），`/health` 可达；`down -v && up` 幂等；镜像内 api 与 algorithm 同装
- **Pass Condition**: 命令输出与 /health 响应留证；本步 compose 仅 db/api（已拍板，web 由前端轮次补）
- **Evidence**: shell 输出

### AC-19: 分层纪律（rubric）
- **Type**: `rubric`
- **Dimension**: 五层边界与依赖方向的纯度（无越层 import、无算法重写、无前端产物）
- **Scale**: 1-5
- **Anchors**: 1 = 路由直连 run_chain/算法被改；3 = 边界大体在但有 1~2 处越层工具函数；5 = import 方向全部向下，后端只做注入/编排/持久化/执行兜底，可静态扫描验证
- **Pass Threshold**: >= 4
- **Evidence**: 代码走读 + import 扫描脚本

### AC-20: 离线测试可独立性（rubric）
- **Type**: `rubric`
- **Dimension**: 不依赖 Docker/key/网络即可验证的业务规则比例与替身质量
- **Scale**: 1-5
- **Anchors**: 1 = 大多数规则必须真库真 key 才能验；3 = 主路径离线但边界用例缺；5 = 除 AC-13~16/18 外全部离线可验，替身按协议注入、无 monkeypatch 私有实现
- **Pass Threshold**: >= 4
- **Evidence**: 离线 pytest 输出与替身装配走读

## Resolved Decisions（已拍板，取代原 Open Questions OQ-1~OQ-5）
- **OQ-1**：本步 compose **不含 web 块**；web 服务与 nginx 配置由前端轮次补齐并首次达成三服务 F9。
- **OQ-2**：集成测试 Done 口径 = **人工 `docker compose up db` 后跑一次 integration 并留输出**；CI/自动化不属本版。
- **OQ-3**：`messages.internal` 落 `{sql, trace, query_spec}` 三键，仅服务端可见、不向前端报文输出（SDD §3.3 字面增补已在 Spec 留痕）。
- **OQ-4**：**先补算法再做后端**——algorithm-chain 增补轮次先行交付 S5 刷新入口与 S4 recalibrate 入口（spec/实现/测试全绿），本步才开始编码；后端不做 stub 长期顶位。
- **OQ-5**：常数默认：`QUESTION_MAX_LENGTH=500`（依 SDD-前端 §3.1 统一，原 1000 已跟随修正）、分页默认 50/上限 200、SSE 事件缓冲 10 分钟、口径摘要 N=5。
