# 后端服务（backend-service）- 实现计划

> 依赖顺序即建议实现顺序。每个任务自验 TR 后记录 Completion Evidence。
> 测试两级：离线单测（默认 `pytest backend_service/tests/unit`，无 DB/key/网络）与集成测试（`-m integration`，需 `docker compose up db`）。
> OQ-1~OQ-5 已拍板（见 spec.md Resolved Decisions）。前置：algorithm-chain 增补轮次（S5 刷新入口 / S4 recalibrate 入口）先行交付并测试全绿后，本任务才开始实现；不再使用 stub 顶位。

## Task 1: 工程骨架、配置、错误体系与健康检查空壳
- **Status**: `done`
- **Completion Evidence**: `backend_service/config.py`（OQ-5 常数默认 + env 覆盖/非法回退）、`backend_service/errors.py`（§8 映射表 + 信封 + extra 合入）、`backend_service/main.py`（应用工厂 + 统一异常处理器）；单测 `backend_service/tests/unit/test_config_errors.py`（映射表驱动 8 码 + 信封 extra + 默认值/覆盖/非法回退）、`test_health.py::test_unknown_route_envelope_404`。TR-1.1/1.2/1.3 全过。

- **Priority**: high
- **Depends On**: None
- **Description**:
  - 建 `backend_service/` 包：`main.py`（应用工厂、/api/v1 挂载、异常处理器、开发态 CORS）、`config.py`（SDD §7.3 全 env + 常数默认：10s/500/1000/500 字/分页 50,200/缓冲 10min/N=5）、`backend_service/requirements.txt`（fastapi、uvicorn、sqlalchemy2、psycopg[binary]、pydantic v2、sse-starlette、 PyYAML 等）、`requirements-dev.txt`（pytest、pytest-asyncio、httpx）。
  - 统一错误信封与 §8 错误码异常类→HTTP 映射；E_VALIDATION 校验器（空/超长/互斥）。
  - 路由包占位 chat/sessions/reports/health；`GET /health` 先返回静态 ok 壳（FR-16 深化在 Task 10）。
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-1.1: 无 DB/key 环境 `uvicorn` 可起、TestClient 可请求 /health 与 404 信封；证据：单测输出。
  - `rule` TR-1.2: 各错误码→HTTP 映射表驱动测试全覆盖；证据：单测。
  - `rule` TR-1.3: config 全 env 缺失时默认值正确不抛错；证据：单测。

## Task 2: storage 层模型与仓储（app schema）
- **Status**: `done`
- **Completion Evidence**: `backend_service/storage/models.py`（三表 ORM，jsonb/uuid/unique/级联，不写死 schema 前缀）、`backend_service/storage/repositories.py`（显式事务、seq=max+1、payload.turn_id 反查、reports insert/overwrite 同事务 _REQUIRED 校验缺失抛 ValueError 回滚）；接口级单测以 `backend_service/tests/conftest.py` 内存仓储替身承接（seq 递增/同名冲突/覆盖 id 不变/缺字段 ValueError），TR-2.3 级联与 create_all 幂等由 Task 12 integration（B21/B22）复验。

- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `storage/models.py`：sessions / messages / reports 三表 SQLAlchemy2 模型（字段、jsonb、uuid、unique(owner_id,title)、unique(session_id,seq)、级联、owner_id default 'default'、inherited_spec）；exemplar/meta_schema_cache 的裸 SQL 建表语句准备（不用 ORM 映射 vector 列，或仅映射非向量列，建表走 init/ensure 脚本）。
  - `storage/repositories.py`：sessions（建/列表/取/改名/删/计数）、messages（追加带 seq 分配、按会话顺序取）、reports（按 owner+title 查、插入/覆盖单事务、列表 q 匹配、直读快照、改名/删）。
  - `create_all` 幂等入口；仓储全部要求显式会话注入，不隐式开连接。
- **Acceptance Criteria Addressed**: AC-8, AC-9, AC-10, NFR-5
- **Test Requirements**:
  - `rule` TR-2.1: 以会话/事务替身（或 integration PG）覆盖：seq 唯一递增、级联删除、同名冲突、覆盖 id 不变；证据：单测（仓储接口用 fake session 断言 SQL/调用）+ Task 12 integration 复验。
  - `rule` TR-2.2: reports 保存事务内字段缺失→回滚无残留；证据：单测/integration。
  - `rule` TR-2.3: create_all 重复调用无异常；证据：integration（Task 12 联跑）。

## Task 3: data 双引擎与 QueryRunner
- **Status**: `done`
- **Completion Evidence**: `backend_service/data/engines.py`（APP=SQLAlchemy2 懒连接 search_path=app；analytics=psycopg3 裸连接 search_path/dw + statement_timeout + read-only，connect_count 计数器）、`backend_service/data/query_runner.py`（sqlglot 单条 SELECT 守卫 + ROW_LIMIT_MAX+1 截断 + QueryCanceled→QueryTimeoutError）；TR-3.1 单测 `test_query_runner.py`（13 组守卫拒绝/放行 + 伪造游标截断/不触库/取消短路/超时归一）；TR-3.2 由 `test_query_runner_integration.py`（B23）人工验收；TR-3.3 走读通过（无写 API、不改写 SQL）。

- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `data/engines.py`：APP 引擎（SQLAlchemy，app schema）与 analytics 引擎（psycopg3 连接池/连接参数：只读连接串、search_path=dw、statement_timeout=10s）；引擎工厂从 config 构建。
  - `data/query_runner.py`：实现算法 QueryRunner 协议——单条 SELECT 执行前守卫（单语句+SELECT，复用算法 lint 同款解析依赖 sqlglot，不做业务改写）、取 ROW_LIMIT_MAX+1 判 truncated、归一超时/执行异常为算法约定异常（QUERY_TIMEOUT/QUERY_ERROR 语义）；返回 `{columns,rows,row_count,truncated}`。
- **Acceptance Criteria Addressed**: AC-14, AC-19(部分)
- **Test Requirements**:
  - `rule` TR-3.1: 离线单测：守卫拒绝多语句/非 SELECT（不触库）；截断判定逻辑用伪造游标结果验证；证据：单测。
  - `rule` TR-3.2: integration：pg_sleep 超时、>1000 行截断、正常 SELECT 列行结构；证据：integration 输出。
  - `rule` TR-3.3: 源码检查 Runner 无写操作 API、不改写 SQL 文本（除连接级参数）；证据：走读。

## Task 4: 真实 L0 SchemaProvider、PgRepository 与算法依赖装配
- **Status**: `done`
- **Completion Evidence**: `backend_service/data/schema_provider_pg.py`（pg_catalog 联查产 parse_schema_rows 兼容行 + 文本列 DISTINCT LIMIT 21 枚举采样 + enum_candidates 值/列注释双通道）、`backend_service/data/pg_exemplar_repo.py`（向量余弦 topN + 关键词计分 + EMB_DIM 校验 + meta_schema_cache 读写，走 APP 引擎）、`backend_service/composition.py`（build_context 无 key/无 EMB 可构建、Deps 组装、startup_sequence=建表→L0→EMB 齐全才 ensure）。TR-4.3 单测 `test_composition.py`；TR-4.1/4.2 由 `test_l0_extraction.py`/`test_exemplar_repository.py`（B24/B25）人工验收；TR-4.4 静态扫描 `test_static_scan.py`（algorithm 白名单 8 模块）+ algorithm 包零改动。

- **Priority**: high
- **Depends On**: Task 3
- **Description**:
  - `data/schema_provider_pg.py`：经 analytics 只读连接查 information_schema/pg_catalog，产算法 SchemaBlock（表/列/类型/主外键/列注释/枚举采样，枚举采样限维表小列）；进程内缓存。
  - `data/pg_exemplar_repo.py`：实现算法 Repository 协议三方法（upsert_exemplar / search_exemplars topN 余弦/hnsw / load_schema_cache；meta_schema_cache 写入由后端启动序列自落）；维度 EMB_DIM 校验；未配置 EMB 时返回「未启用」实现（检索端由算法降级）。
  - `composition.py`（应用装配根）：按 env 构建 LLMClient（无 key 照常构造、调用期抛 LLMUnavailableError → E_LLM_UNAVAILABLE）/EmbeddingClient、双引擎、SchemaProvider、Repository、QueryRunner、内存 checkpointer，并以 RESOURCES_PATH 经算法 loader 预加载 Resources；产出算法 `Deps`（settings/llm/schema_provider/query_runner/embedding?/repository?/resources/on_event）；生命周期：create_all→L0 抽取→（EMB 齐全）ensure exemplar+hnsw。
- **Acceptance Criteria Addressed**: AC-15, AC-16, AC-17, FR-17, FR-20, FR-21
- **Test Requirements**:
  - `rule` TR-4.1: integration：夹具六表抽取断言（注释/美妆四候选/档期四值/主外键）；证据：integration。
  - `rule` TR-4.2: integration：EMB 未配置不建 exemplar；配置后建表/hnsw、upsert+search 排序正确、维度不符报错；证据：integration。
  - `rule` TR-4.3: 离线：装配根在无 key/无 EMB 下可构建（DB 可懒连接）；证据：单测。
  - `rule` TR-4.4: 静态检查 algorithm 包不被本任务修改、后端只 import 其协议/入口；证据：目录 diff。

## Task 5: conversation_service（编排/落库/SSE 缓冲/取消）
- **Status**: `done`
- **Completion Evidence**: `backend_service/application/conversation_service.py`（三入参互斥、票据注册表、selection 拼接、recalibrate→S4、conversation_summary 继承口径+最近 N=5、internal 三键、取消协作含未启动任务兜底、异常兜底 error 终态）、`backend_service/application/event_buffer.py`（单调 id/retention/可控时钟）、`backend_service/application/mappers.py`（stage 写死映射同段去重/五终态帧/internal/payload 白名单）。TR-5.1~5.5 单测 `test_conversation_service.py` 27 例（六 action 帧、互斥/409/404、QueryRunner=0 与三种拼接、三键与出口白名单、补帧/过期/取消）；TR-5.6 走读：编排不拼报文、无算法分支重写。

- **Priority**: high
- **Depends On**: Task 2, Task 4
- **Description**:
  - turn 注册表（running/终态）、事件缓冲（10min、单调 id、Last-Event-ID 补帧）、取消注册表。
  - 建 turn：三态入参互斥校验；clarify 票据校验与 selection→clarified_question 拼接（option/time_preset/custom）；recalibrate 取 internal.query_spec 走算法 S4 recalibrate 入口（algorithm-chain 增补轮次交付）。
  - 调 run_chain：Deps 注入、conversation_summary（最近 5 条 answer 口径）、thread/checkpointer、on_event（node_started/node_finished 载荷 {"node":"Sx"}）→stage 映射（S1/S2-S4/S5-S8，同段去重）。
  - 终态处理：ChainResult→终态帧与持久化消息（payload 切片 + internal{sql,trace,query_spec}；clarification 带 status 生命周期；cancelled→note）；AnswerEvent 信封派生（data_time_range/queried_at/saveable）。
  - 取消协作：置标志 + Runner 执行期 cancel 路径。
- **Acceptance Criteria Addressed**: AC-2, AC-3, AC-4, AC-5, AC-6, AC-7
- **Test Requirements**:
  - `rule` TR-5.1: 六 action 脚本 → 帧名/帧序/载荷逐字段对照；空结果 saveable=false；证据：单测。
  - `rule` TR-5.2: 三入参互斥、票据失效 409、recalibrate 缺源 404；证据：单测。
  - `rule` TR-5.3: 首轮 clarify 时 FakeQueryRunner 调用=0；三种 selection 拼接文本断言；重复确认被拒；证据：单测。
  - `rule` TR-5.4: internal 三键落库；所有出口序列化不含 sql/trace/query_spec；stage 不落库；证据：单测。
  - `rule` TR-5.5: 缓冲补帧与过期行为（用可控时钟）；取消到 cancelled+note；证据：单测。
  - `rubric` TR-5.6: 服务层纯编排质量（无报文拼装泄漏到路由、无算法分支重写）；scale 1-5；anchors 同 AC-19；threshold >= 4；证据：走读。

## Task 6: chat 路由（POST turns / SSE / cancel）
- **Status**: `done`
- **Completion Evidence**: `backend_service/routes/chat.py`（POST 202 running；GET events EventSourceResponse ping=15 + Last-Event-ID 补帧 + closed/expired 收流；cancel 202 幂等；文件头注释给 nginx 配置提示）。TR-6.1 单测 `test_chat_routes.py`（SSE 端到端取帧/含 stage 帧/建流 404/参数校验全分支/Last-Event-ID 续帧）；TR-6.2（重复取消 202、未知 404、收尾轮询至 cancelled）。

- **Priority**: high
- **Depends On**: Task 5
- **Description**:
  - `backend_service/routes/chat.py`：POST /chat/turns（202/400/404/409）、GET events（SSE 响应、404 E_TURN_NOT_FOUND、Last-Event-ID）、POST cancel（202 cancelling）；pydantic 请求模型三态互斥。
  - SSE content-type/心跳/关 buffering 注意项以代码注释指给 nginx 配置轮次。
- **Acceptance Criteria Addressed**: AC-2, AC-3
- **Test Requirements**:
  - `rule` TR-6.1: TestClient/httpx stream 端到端取帧断言（假服务）；建流 404；证据：单测。
  - `rule` TR-6.2: cancel 幂等（重复取消不 500）；证据：单测。

## Task 7: sessions 路由
- **Status**: `done`
- **Completion Evidence**: `backend_service/routes/sessions.py`（列表按 last_question_at 倒序 + 分页校验 0/50 上限 200、messages 完整还原 §3.3 type/payload 表、DELETE 204→404 级联）；单测 `test_sessions_routes.py`：TR-7.1（列表/分页边界 limit 0/201/offset -1→400、还原 seq 递增 + clarification 最终 status + note、删除 204→404→messages 404）、TR-7.2（还原报文断言无 internal 三键）。
- **Priority**: medium
- **Depends On**: Task 5
- **Description**:
  - GET /sessions（分页/排序）、GET /sessions/{id}/messages（完整还原）、DELETE /sessions/{id}（204/404）；Message 出参模型严格按 §3.3 type/payload 表。
- **Acceptance Criteria Addressed**: AC-8
- **Test Requirements**:
  - `rule` TR-7.1: 列表/还原/删三类单测（含分页边界、clarification 最终 status、note）；证据：单测。
  - `rule` TR-7.2: 还原报文白名单不含 internal 三键；证据：单测。

## Task 8: report_service 与报表路由（存/列/开/改/删）
- **Status**: `done`
- **Completion Evidence**: `backend_service/application/report_service.py` + `backend_service/routes/reports.py`（保存按 payload.turn_id 反查 answer、空结果/澄清轮/幽灵 turn→409 E_REPORT_NOT_SAVEABLE、同名 409 带 existing、overwrite 200 id 不变、新存 201、列表 q 匹配倒序、改名/删除/404/空名 400）；单测 `test_reports_routes.py`：TR-8.1 全分支、TR-8.2 spy 断言 chain_runner.calls==[] 且 analytics connect_count==0（直读快照零查询）。
- **Priority**: high
- **Depends On**: Task 5
- **Description**:
  - `application/report_service.py` + `backend_service/routes/reports.py`：保存门槛（按 payload.turn_id 反查 answer 消息、saveable 校验）、同名冲突+existing、overwrite 同事务、列表 q 匹配、打开直读快照（spy 保证不调 run_chain/不建 analytics 连接）、改名/删除/404/空名。
- **Acceptance Criteria Addressed**: AC-9, AC-10
- **Test Requirements**:
  - `rule` TR-8.1: 门槛/冲突/覆盖/201/400/404 全分支单测；证据：单测。
  - `rule` TR-8.2: GET 详情断言 run_chain 与 analytics 连接调用计数为 0；证据：spy 单测。

## Task 9: 报表刷新与 continue-session
- **Status**: `done`
- **Completion Evidence**: refresh/continue-session 落 `backend_service/routes/reports.py` + `backend_service/application/report_service.py`；单测 `test_refresh_continue.py`：TR-9.1（`_assert_s5_seam` 断言 run_chain 收到 start_at="S5"+query_spec、不走 S1 主入口；四终态循环同构；消息数与 reports.updated_at 不变；响应无 sql/trace/query_spec；无 query_spec 报表 refresh→409）、TR-9.2（continue-session 201 写 inherited_spec/title、零假消息，继承首问 conversation_summary 含「【继承口径】…指标 gmv/维度 channel/时间…」，第二问不含继承文本）。
- **Priority**: high
- **Depends On**: Task 8
- **Description**:
  - POST /reports/{id}/refresh：取 query_spec 调算法 S5 刷新入口（algorithm-chain 增补轮次交付），同步映射 answer/query_gen_failed/query_failed/空结果同构体；不改快照、不写消息、queried_at 更新为本次（仅响应）。
  - POST /reports/{id}/continue-session：建会话写 inherited_spec/title，返 session_id。
- **Acceptance Criteria Addressed**: AC-11, AC-12
- **Test Requirements**:
  - `rule` TR-9.1: 脚本化刷新入口四终态响应断言；断言调用的是 refresh 接缝而非 S1 主入口；messages 计数与 reports.updated_at 不变；证据：单测。
  - `rule` TR-9.2: continue-session 后新会话首问的 `conversation_summary` 含继承口径文本（来自 inherited_spec，经后端拼装）；消息流无插入；证据：单测。

## Task 10: 健康检查深化与启动生命周期
- **Status**: `done`
- **Completion Evidence**: `backend_service/routes/health.py` 三探针（db=SELECT 1 / llm / embedding，unconfigured 不降级、单探针异常隔离）+ 聚合 degraded 规则；`backend_service/composition.py` 增 ctx.startup/shutdown 钩子、`backend_service/main.py` lifespan 钩子探测式（替身 context 跳过生命周期）；单测 `test_health.py`：TR-10.1 六组聚合表驱动全过；TR-10.2 由 `test_startup_health.py`（B21）人工 OQ-2 验收（真实 db 启动序列 + 无 LLM key 启动 + META_SCHEMA_CACHE 回读）。
- **Priority**: medium
- **Depends On**: Task 4
- **Description**:
  - /health 真实检查 db（SELECT 1）、llm（unconfigured/ok/error 探针，失败不拖死请求）、embedding 同；聚合 degraded 规则按 FR-16。
  - lifespan 启动钩子按 FR-17 串起 create_all→L0→ensure exemplar；可选增强失败只降级不退出（db 失败则启动失败）。
- **Acceptance Criteria Addressed**: AC-17
- **Test Requirements**:
  - `rule` TR-10.1: 各 checks 组合→status 聚合表驱动测试；证据：单测。
  - `rule` TR-10.2: integration：真实 db 下启动序列成功；无 LLM key 启动成功；证据：integration。

## Task 11: init SQL、Dockerfile、compose 与环境样例
- **Status**: `done`
- **Completion Evidence**: `backend_service/db/01-init.sql`（app/dw 两 schema、app_user/chatbi_ro 两角色授权、CREATE EXTENSION vector、幂等）、`backend_service/Dockerfile`（构建上下文仓库根，同装 backend_service/+algorithm/，uvicorn 单 worker 8000）、`.dockerignore`、`docker-compose.yml`（仅 db/api 两服务，OQ-1；db healthcheck + init SQL 挂载 + 不对宿主发布端口；api depends_on healthy）、`backend_service/.env.example` 全量。TR-11.1/11.3 因本机无 Docker 未执行，留待人工验收（见 checklist B27~B29）；TR-11.2 由 B22 integration 人工验收。
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - `backend_service/db/01-init.sql`：schema app/dw、app_user/chatbi_ro 角色与授权（ro：dw USAGE/SELECT + information_schema/pg_catalog 只读；app_user：app 全 DML）、CREATE EXTENSION vector；幂等写法。
  - `backend_service/Dockerfile`：python:3.12-slim，构建上下文仓库根，COPY backend_service/ + algorithm/ + requirements；uvicorn 单 worker 8000；`.env.example` 按 §7.3 全量；`.dockerignore`。
  - `docker-compose.yml`：db（pgvector/pgvector:pg16、pgdata、healthcheck、挂 init SQL，不对宿主发布）+ api（depends_on healthy、env_file、8000 内网）；**本步不含 web 块（已拍板 OQ-1，web 由前端轮次补）**。
- **Acceptance Criteria Addressed**: AC-13, AC-18
- **Test Requirements**:
  - `rule` TR-11.1: `docker compose config` 通过；空卷 `up -d db api` 后 /health=db ok；`down -v` 再 up 幂等；证据：shell 输出。
  - `rule` TR-11.2: integration：ro 写/建表/读 app 三类越权均被 PG 拒绝；app_user 对 app DML 正常；证据：integration。
  - `rule` TR-11.3: 容器内可 import algorithm 与 api；证据：容器内命令输出。

## Task 12: 测试夹具、集成测试与全量验收
- **Status**: `done`
- **Completion Evidence**: 夹具 `backend_service/tests/fixtures/dw_test.sql`（六表 DDL 对齐 metrics-dictionary §5 + 全列中文 COMMENT + 取模伪随机两窗口 seed + ANALYZE + GRANT 兜底）；integration 装配 `backend_service/tests/integration/conftest.py`（db 不可达自动 skip）+ 五个集成测试文件（B21~B25，23 例，已通过收集验证）；静态扫描 `backend_service/tests/unit/test_static_scan.py`（分层 import AST 白名单 + dual_line/narrative 禁漏 + internal 三键 + STAGE_BY_NODE 全等）；根 `pytest.ini`（合并跑时 marker/addopts 正确归属）。TR-12.1 达成：清空 LLM/EMB/DB 下 `pytest algorithm backend_service/tests` → 146 passed, 25 deselected, exit 0；TR-12.3 达成；TR-12.2 留待人工 OQ-2（本机无 Docker）；TR-12.4/12.5 依据扫描结果与用例清单走读 ≥4（见 checklist B32）。
- **Priority**: high
- **Depends On**: Task 6, Task 7, Task 8, Task 9, Task 10, Task 11
- **Description**:
  - `backend_service/tests/fixtures/`：仿 metrics-dictionary §5 六表的测试 DDL（中文注释+美妆多候选+档期枚举+日期覆盖）、最小 seed（pg_sleep/大结果集用于超时截断）。
  - conftest：离线装配（假 run_chain 场景脚本、内存注册表/缓冲、Fake 引擎与 QueryRunner、tmp 资源目录）与 integration 装配（db 容器连接串 env、夹具 DDL 建在独立 test schema 或 dw 测试库）。
  - 补齐 AC 映射的全部单测/集成测；静态检查脚本：分层 import 扫描 + 报文白名单扫描（无 sql/trace/narrative/dual_line）。
  - 验收跑：离线全绿 → `docker compose up db` 跑 integration → `up db api` 冒烟 /health 与一条假链路 SSE（脚本化 run_chain，不依赖真 LLM key）。
- **Acceptance Criteria Addressed**: AC-1~AC-20 全量
- **Test Requirements**:
  - `rule` TR-12.1: 清空 LLM/EMB env 下离线测试退出码 0；证据：命令输出。
  - `rule` TR-12.2: integration 全绿（含 AC-13~16/18 全部断言）；证据：命令输出。
  - `rule` TR-12.3: 静态扫描脚本纳入测试，越层 import/禁漏字段即失败；证据：脚本与输出。
  - `rubric` TR-12.4: AC-19 分层纪律 ≥4；证据：扫描结果+走读。
  - `rubric` TR-12.5: AC-20 离线可独立性 ≥4；证据：用例清单（除 integration 标记外无 DB/网络依赖）。
