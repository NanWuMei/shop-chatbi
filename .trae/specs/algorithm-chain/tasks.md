# 算法问数链路（algorithm-chain）- 实现计划

> 任务顺序即依赖顺序；无真库、无 key、无网络是全程默认前提。每个任务完成后必须自验 TR 并记录 Completion Evidence。
> 状态：Task 1~15 已全部交付（pytest 46 用例全绿 = 既有 34 回归 + Task 15 新增 12）；中段入口（S5 刷新 / S4 recalibrate）已就绪，后端步（backend-service Task 1~12）可开工。

## Task 1: 工程骨架、配置与全部强类型契约
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 建 `algorithm/` 包骨架（`__init__.py`）与 SDD §5 模块树列出的全部目录/占位文件（agents 四个子包、nodes、retrieval、llm、resources/dict、resources/templates）。
  - `algorithm/requirements.txt` 按 SDD 锁定 langgraph/langchain/langchain-openai/psycopg[binary]，并按 spec OQ-1 写入 sqlglot（以批准结果为准）；测试依赖写入 `algorithm/requirements-dev.txt`（pytest、pytest-asyncio、pyyaml）。
  - `algorithm/config.py`：env 读取（LLM_*/EMB_*/RESOURCES_PATH 及超时/限幅默认值 30s、500/1000），纯函数式 Settings，无 key 不报错。
  - `algorithm/state.py`：SDD §6 的全部强类型——ChainResult（六 action 枚举、四载荷互斥）、ChainState 黑板、IntentSpec/QuerySpec/ComparisonSpec/RetrievalContext/TemplateMatch/QueryResult/TableData/ChartSpec/clarify/rejection/error/trace/meta；chart 五型枚举、四 clarify 码、六 rejection 码、E_LLM_UNAVAILABLE。
  - `algorithm/protocols.py`：Protocol 定义——LLMClient（complete 结构化）、EmbeddingClient（embed）、SchemaProvider（all_blocks 等）、QueryRunner.run、Repository（search_exemplars/upsert_exemplar/load_schema_cache）、Deps 聚合、OnEvent 回调签名（node_started/node_finished/terminal）。
- **Acceptance Criteria Addressed**: AC-2, AC-14, NFR-2, NFR-3
- **Test Requirements**:
  - `rule` TR-1.1: `python -c "import algorithm"` 与逐子模块 import 全成功（无任何环境依赖）；证据：命令输出。
  - `rule` TR-1.2: ChainResult 构造测试——六 action 各构造一次；同一结果强制两载荷非空时校验失败；空结果 answer（rows=[]/chart=null/caliber 存在）可构造；证据：pytest 契约单测。
  - `rule` TR-1.3: 字段名/枚举值与 SDD §6 文本逐项比对（枚举成员清单作为测试常量，缺任一即 fail）；证据：单测源码与通过输出。
  - `rule` TR-1.4: Settings 在全 env 缺失时返回默认值且不抛错；证据：单测。
- **Notes**: 占位节点文件只写模块 docstring（引用 SDD 对应小节），不提前实现；pydantic v2 随 langchain 可用，优先 pydantic 做载荷模型。

## Task 2: LLM/Embedding 客户端、双档 registry 与 mock 实现
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `llm/client.py`：OpenAI 兼容实现（chat completions + structured output；base_url/api_key/model/timeout 全参数注入；`complete` 内失败重试 1 次；不合 schema 视同失败）；工厂延迟构建（无 key 不在 import/build 期报错，问数时才产生 E_LLM_UNAVAILABLE）。
  - `llm/embeddings.py`：OpenAI 兼容 embed 实现 + 进程内 TTL 缓存（同文本 5 分钟）；未配置即不可用的显式信号（供 S3 降级判断）。
  - `llm/registry.py`：节点 → fast/strong → 具体模型的解析（Understand/Writer=fast，Aligner/Coder=strong；缺档回落 LLM_MODEL）。
  - `algorithm/tests/mocks/`：MockLLMClient（按 agent 名 + 场景 id 返回 canned 结构，可脚本化连续调用/抛错）、MockEmbeddingClient（确定性伪向量 + 可切换抛错）；MockLLM 同时记录调用次数/档位供断言。
- **Acceptance Criteria Addressed**: AC-13, AC-3, NFR-1
- **Test Requirements**:
  - `rule` TR-2.1: 无任何 LLM env 时 import algorithm + build 依赖容器不抛错；证据：单测。
  - `rule` TR-2.2: registry 四节点档位断言（fast/strong/回落逻辑三组）；证据：单测。
  - `rule` TR-2.3: mock 客户端可脚本化「成功/连续抛错/结构化不合规」，并记录 llm_calls；证据：mock 自测。
  - `rule` TR-2.4: 生产客户端代码无厂商名字面量；证据：grep 检查（仅 OpenAI 兼容协议词与 env 名允许出现）。
  - `rule` TR-2.5: embed 缓存同文本第二次不重复计数；证据：单测。

## Task 3: L0 静态快照、SchemaBlock 模型与抽取解析器
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 建 `tests/fixtures/l0/l0_schema.json`：metrics-dictionary §5 六表完整快照（表/列/类型/主外键/中文列注释/枚举采样）。枚举必须含：渠道 A/B/C/D、预热/正式/返场/日常、美妆多候选（美妆个护/彩妆/护肤/美妆工具）、支付状态；日期覆盖声明 2025-06-01~2026-06-30（2025 仅 6 月窗口）。
  - `retrieval/schema_extractor.py`：①「information_schema/pg_catalog 查询结果行 → SchemaBlock」纯解析函数（为后端步真抽取预留）；② 本步不写任何真实连接代码。
  - `StaticSchemaProvider`（tests/mocks 或 tests/fixtures 加载器）实现 SchemaProvider：all_blocks、按表名/关键词取块、枚举采样查询。
- **Acceptance Criteria Addressed**: AC-6, AC-14, AC-16
- **Test Requirements**:
  - `rule` TR-3.1: 快照六表/字段/注释/枚举可被加载且与 metrics-dictionary §5 关键字段清单逐项对应；证据：快照结构单测。
  - `rule` TR-3.2: 「美妆」枚举查询返回 ≥4 个跨层级候选；档期枚举为四值；证据：单测。
  - `rule` TR-3.3: 解析器对样例 information_schema 行（fixture 附带最小样例）产出正确 SchemaBlock；证据：单测。
  - `rule` TR-3.4: algorithm 包源码 grep 不到 psycopg/connect/真实驱动调用；证据：静态检查。
  - `rubric` TR-3.5: L0 快照业务保真度；scale 1-5；anchors 同 AC-16（占位 1 / 有出入 3 / 可逐条对照 5）；threshold >= 4；证据：对照 metrics-dictionary §2/§4.1/§5 走读快照。

## Task 4: L1/模板资源加载、Repository 协议与 lexical 通道
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 3
- **Description**:
  - `resources/loader.py`：从注入路径加载 dict/*.yaml 与 templates/*.yaml；路径缺失/目录为空 → 空资源对象，不报错；建空 `resources/dict/.gitkeep`、`resources/templates/.gitkeep` 与 `agents/writer/style_examples.yaml`（1~2 条只控格式的风格示例，不含业务数字）。
  - `retrieval/repo.py`：Repository 协议实现类 `InMemoryRepository`（exemplars 增/查 + schema cache 读写）。
  - `retrieval/lexical.py`：关键词通道——对指标/维度/时间词与 schema 块名/注释、L1 别名、exemplar 文本做匹配打分排序。
- **Acceptance Criteria Addressed**: AC-4, AC-5, AC-18, AC-19
- **Test Requirements**:
  - `rule` TR-4.1: 空目录/不存在路径加载返回空资源且不抛错；证据：单测。
  - `rule` TR-4.2: fixtures 临时 YAML（1 条 dict、1 条模板）能被加载并被 lexical 命中；证据：单测。
  - `rule` TR-4.3: lexical 对「渠道 GMV」「美妆」类关键词返回相关 schema 块且按分排序；证据：单测。
  - `rule` TR-4.4: InMemoryRepository 的 exemplar upsert/search 与 schema cache 读写行为正确；证据：单测。
  - `rule` TR-4.5: style_examples.yaml 不含任何具体业务数字；证据：文件审查。

## Task 5: S3 Retrieve 节点与 vector 通道
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2, Task 3, Task 4
- **Description**:
  - `retrieval/vector.py`：embed 问题文本 → 经 Repository 取 exemplar 向量做余弦排序 top3~5；embedding 客户端不可用/抛错时抛出明确的「降级信号」，不自行兜底吞错。
  - `nodes/retrieve.py`：编排四源——L0 schema_blocks（必有）、L1 caliber/entity（有则）、exemplars（vector 成功则向量 top3~5，失败/未配置回 lexical 关联）；输出 RetrievalContext 与 mode（vector/lexical）；L0 为空时返回空上下文。
- **Acceptance Criteria Addressed**: AC-5
- **Test Requirements**:
  - `rule` TR-5.1: 未配 EMB_* → mode=lexical、不抛错、trace 可记录；证据：单测。
  - `rule` TR-5.2: embed 抛错 → mode=lexical；正常 → mode=vector 且 exemplars ≤5 按相似度降序；证据：单测。
  - `rule` TR-5.3: schema_blocks 在 L0 快照存在时恒非空；空 SchemaProvider 时上下文为空且节点正常返回；证据：单测。
  - `rule` TR-5.4: RetrievalContext 是只读数据对象，节点内无任何授权判定分支；证据：代码走读。

## Task 6: S1 Understand 智能体
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `agents/understand/agent_schemas.py`：IntentSpec pydantic 模型（指标/维度/时间表达/对比意图/过滤/排序/TopN/槽位形态/是否数据问题判定字段）。
  - `agents/understand/prompts.py`：系统提示词（只「听懂」不猜表、不授权；归因/预测/闲聊识别；输出严格 schema）。
  - `agents/understand/node.py`：调 fast 档 LLM 结构化输出→IntentSpec；非数据问题 → 终态 not_answerable(NOT_DATA_QUESTION)（含固定业务文案与 suggestions 构造）；异常重试 1 次后 error(E_LLM_UNAVAILABLE, retryable=true)；支持会话口径摘要输入（T12 指代基础）。
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-6.1: T15 脚本能稳定产出 not_answerable + NOT_DATA_QUESTION + 非空 suggestions；reason_text 无技术码/SQL；证据：单测。
  - `rule` TR-6.2: T01/T03/T07/T12 脚本产出 IntentSpec 关键字段（指标/维度/时间/对比/排序）断言；证据：单测。
  - `rule` TR-6.3: LLM 持续抛错时恰好重试 1 次（总调用 2）后 error 终态；证据：单测读 mock 调用记录。
  - `rule` TR-6.4: 节点代码不引用任何表名/白名单/Repository；证据：import/源码检查。

## Task 7: S2 TemplateMatcher 规则节点
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 4, Task 6
- **Description**:
  - `nodes/template_match.py`：规则匹配——IntentSpec 槽位与模板骨架对齐；仅当槽位填满、无模板外新约束时 hit=true，产出填好的 SQL/chart_type/bindings/template_id；否则未命中。不调 LLM。
  - 模板 YAML 解析（骨架/槽位/SQL 模板/图型）复用资源加载器。
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-7.1: 空模板库 → hit=false 且无异常；证据：单测。
  - `rule` TR-7.2: fixtures「{time}各渠道 GMV」模板 + T01 槽位脚本 → hit=true、SQL 绑定含绝对区间占位替换、chart_type 有值；证据：单测。
  - `rule` TR-7.3: 槽位缺失/出现模板外过滤 → hit=false；证据：单测。
  - `rule` TR-7.4: 节点源码不 import 任何 LLM 客户端；证据：检查。

## Task 8: S4 Aligner 智能体与 clarify 节点
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5, Task 6
- **Description**:
  - `agents/aligner/agent_schemas.py`：对齐输出 schema——QuerySpec（指标→表/列/聚合/口径过滤、维度→列、时间→起止日期、实体展开、排序、limit）、ComparisonSpec（mode/periods/value_fields）、多候选/缺时间/指代失败/无匹配/口径矛盾的结构化分支字段。
  - `agents/aligner/prompts.py`：基于 IntentSpec×RetrievalContext 对齐；无 L1 时依列名/注释推断并要求输出 caliber 文案；档期词归一（有 L1 calendar 用配置，无则按常识推并标注 inferred）；数据覆盖判断（2025 仅 6 月窗口）。
  - `agents/aligner/node.py`：调 strong 档；按结构化分支设置路由状态（规格钉死/四澄清码/两拒答码）。
  - `nodes/clarify.py`：构造 clarify 载荷（options 来自 L0 层级/枚举候选或 L1 增强、title/input_type/suggestions/allow_custom_text）；round 计数与两轮上限的状态推进。
- **Acceptance Criteria Addressed**: AC-6, AC-12, AC-14
- **Test Requirements**:
  - `rule` TR-8.1: T09/T05 美妆脚本（无任何 L1 文件）→ clarify/METRIC_DIM_AMBIGUOUS，options 含 L0 多候选、确认前状态中无 sql；证据：单测。
  - `rule` TR-8.2: T10 → not_answerable/NO_MATCHING_DATA + 引导四指标 suggestions；类目转化率脚本 → CALIBER_CONFLICT + 渠道口径建议；证据：单测。
  - `rule` TR-8.3: 缺时间脚本 → clarify/MISSING_TIME/time_quick；指代失败 → ANAPHORA_UNRESOLVED；证据：单测。
  - `rule` TR-8.4: T06 无 L1 脚本产出 QuerySpec 且 caliber.summary/detail 明示「支付订单数」分母；T07 periods=3 段绝对日期；T08 mode=yoy 且 2025 窗口内不拒答；证据：单测。
  - `rule` TR-8.5: 第二轮仍未消歧脚本推进后状态指向 not_answerable（终态组装在 Task 13 集成断言）；证据：状态断言。

## Task 9: S5 Coder 子图（gen + sqlglot lint + 自环）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 8
- **Description**:
  - `agents/coder/agent_schemas.py`：生成输出（sql + lineage：表/列/口径/exemplar_ids）。
  - `agents/coder/prompts.py`：QuerySpec + L0/L1/示例上下文翻译成单条 SELECT；示例只作写法参考。
  - `agents/coder/gen.py`：调 strong 档生成。
  - `agents/coder/lint.py`：sqlglot AST 校验——① 表白名单 ∈ L0；② 列归属 ∈ 该表列；③ 仅单条 SELECT（禁多语句/DDL/DML/写操作）；④ LIMIT 缺失/超限时注入/压到上限（默认 500、硬顶 1000，可注入）；不通过回结构化 lint 错误。
  - `agents/coder/subgraph.py`：gen→lint 回边，lint_rounds ≤2；超轮 → query_gen_failed(GEN_LINT_EXHAUSTED) 带原因；lint_passed 显式布尔路由。
- **Acceptance Criteria Addressed**: AC-7, AC-10(部分), NFR-5
- **Test Requirements**:
  - `rule` TR-9.1: 合规 SELECT（含 CTE/UNION ALL 对比写法）通过；证据：单测。
  - `rule` TR-9.2: DROP/UPDATE/多语句/注释夹带 → 拒绝；白名单外表/不存在列 → 拒绝；证据：单测各 ≥1 例。
  - `rule` TR-9.3: 无 LIMIT → 自动注入 500；SQL 自带 LIMIT 5000 → 压到 1000；证据：单测。
  - `rule` TR-9.4: 首轮不过二轮过 → lint_passed=true、lint_rounds=2；两轮不过 → 终态 query_gen_failed/GEN_LINT_EXHAUSTED 且 rejection 含 lint 原因；证据：子图测试。
  - `rule` TR-9.5: lineage 表/列集合 ⊆ L0 快照；证据：单测。
  - `rule` TR-9.6: coder 包不 import QueryRunner/execute；证据：import 检查。

## Task 10: S6 Executor 节点与 MockQueryRunner
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 9
- **Description**:
  - `nodes/execute.py`：取状态中的 SQL（S2 模板或 S5 产出）调注入 QueryRunner；映射 QueryResult；超时 → QUERY_TIMEOUT、异常 → QUERY_ERROR（业务大白话 reason_text，不吞异常进 trace）；0 行照常前进。
  - MockQueryRunner（tests/mocks）：按场景脚本返回 columns/rows/truncated，支持脚本化「超时」「抛错」「0 行」「正常」；记录被执行 SQL 与调用次数（供「确认前不出数」断言）。
- **Acceptance Criteria Addressed**: AC-8
- **Test Requirements**:
  - `rule` TR-10.1: 正常脚本 → QueryResult 入状态并继续；0 行 → rows=[] 且不产拒答；证据：单测。
  - `rule` TR-10.2: 超时脚本 → QUERY_TIMEOUT；抛错脚本 → QUERY_ERROR；rejection 文案无 SQL/堆栈；证据：单测。
  - `rule` TR-10.3: execute 只经协议拿连接能力，包内无任何驱动连接代码；证据：grep。
  - `rule` TR-10.4: MockQueryRunner 调用日志可断言次数与 SQL；证据：mock 自测。

## Task 11: S7 Presenter（表/图映射 + 对比 Decimal 计算）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 10
- **Description**:
  - `nodes/build_view.py`：纯规则——按 QuerySpec 形态选图（排名 bar/趋势 line|trend_line/对比 grouped_bar|trend_line/占比 pie/单标量 null/空 null）；组装 TableData（field/label/format、truncated、display_limit）与 ChartSpec（x_field/series/switchable）。
  - 同模块内私有函数：对比 changes 的 Decimal 计算（value_delta 金额 2 位、rate_delta 率 1 位；缺段/分母 0 → None）；period 齐备性校验（缺段如实空）。
- **Acceptance Criteria Addressed**: AC-9, AC-10, NFR-5
- **Test Requirements**:
  - `rule` TR-11.1: 六类形态图型断言（T01 bar、T03 trend_line、T07 grouped_bar、T13 pie、T06 null、空结果 null）；证据：单测。
  - `rule` TR-11.2: TableData/ChartSpec 字段齐备且 label 取自规格业务名；证据：单测。
  - `rule` TR-11.3: 已知输入手算 changes 对照（含小数舍入与分母 0 → None、缺段）；全程 Decimal（源码无 float 参与运算）；证据：单测 + 源码检查。
  - `rule` TR-11.4: 节点不 import LLM 客户端；证据：检查。

## Task 12: S8 Writer 智能体（一句解读 + 落地校验 + 兜底）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 11
- **Description**:
  - `agents/writer/agent_schemas.py`：单句字符串输出 schema。
  - `agents/writer/prompts.py`：只给真实行 + caliber + ChartSpec + changes + 风格示例；禁止建议/归因/预测；空结果固定语义。
  - `agents/writer/node.py`：调 fast 档；数字落地校验器（正则抽数字→归一化格式化→逐一匹配真实行/changes，容差）；失败重生成 1 次；再失败走规则模板句（按规格/行拼装，trace 标注 writer_fallback=true）；任何失败不改变 action=answer。
- **Acceptance Criteria Addressed**: AC-11
- **Test Requirements**:
  - `rule` TR-12.1: 合规句（数字均在行内）通过且恰为一句；证据：单测。
  - `rule` TR-12.2: 含行外数字脚本 → 触发重生成；持续违规 → 模板句兜底、trace 标注、终态仍 answer；证据：单测 + mock 调用次数。
  - `rule` TR-12.3: 空行 → 「该范围无数据」语义句；证据：单测。
  - `rule` TR-12.4: 对比脚本解读只含方向/幅度无原因词（因为/由于/建议 等关键词扫描）；证据：单测。
  - `rule` TR-12.5: 节点输入对象中不存在 SQL 字段可达性（源码不 import execute/state 中不取 sql）；证据：源码走读。

## Task 13: 主图编排、run_chain、checkpointer 与终态组装
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 7, Task 8, Task 9, Task 10, Task 11, Task 12
- **Description**:
  - `graph.py`：注册 8 节点与条件边（S2 分叉、S4 分叉、Coder 子图接入、终态短路）；Coder 为 compiled subgraph；MemorySaver checkpointer 装配（生产可换）。
  - `run_chain(question=..., clarified_question=..., clarify_id=..., deps=..., thread_id=..., on_event=None)`：初始化 trace（start/path/llm_calls）、节点回调（node_started/node_finished/terminal）、澄清重入槽位恢复与 round 推进、终态 ChainResult 组装与载荷互斥保证、elapsed_ms。
  - 两轮澄清仍未消歧 → not_answerable；过程状态不进 ChainResult。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-12, FR-4, NFR-4
- **Test Requirements**:
  - `rule` TR-13.1: T01 未命中路径 trace.path ＝ S1,S3,S4,S5,S6,S7,S8；S2 命中脚本 path ＝ S1,S2,S6,S7,S8；证据：集成单测。
  - `rule` TR-13.2: on_event 收到的节点事件序列与 path 一致，终态事件携带 action；证据：单测。
  - `rule` TR-13.3: 澄清重入（同 thread_id 两次调用）恢复槽位、第二轮后转 not_answerable；证据：单测。
  - `rule` TR-13.4: 六 action 各有一条端到端组装断言（载荷互斥、trace/meta 齐备）；证据：单测。
  - `rule` TR-13.5: 路由函数源码只读取 ChainState 字段，无字符串 contains 式判断；证据：走读。

## Task 14: T01~T15 离线回归套件与全链路验收
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 13
- **Description**:
  - `tests/fixtures/scenarios/t01.yaml … t15.yaml`：每条含原始问法、mock LLM 分节点脚本、MockQueryRunner 行数据、期望（action、图型/chart=null、关键口径字段、reason_code、limit/periods 等），文案与 `docs/测例.md` 逐字对应。
  - `tests/fixtures/rows/`：各场景行数据（渠道 A 领先、美妆类退货率 >8%、日粒度起伏、2026 vs 2025 同比有方向、新老客不极端——按 metrics-dictionary seed 故事）。
  - `conftest.py`：默认装配（静态 L0、空资源目录、mock LLM/embedding、内存 repo、内存 checkpointer、MockQueryRunner）；参数化跑 15 场景。
  - 专项测试：S2 命中 vs 空库、lexical 降级、lint 超轮、query 超时/错误、LLM 不可用、空结果、澄清两轮、重入恢复、无 key build、import 边界静态检查脚本。
- **Acceptance Criteria Addressed**: AC-15, AC-16, AC-17, NFR-1
- **Test Requirements**:
  - `rule` TR-14.1: 清空环境变量（unset LLM_*/EMB_*）且无 DB 进程下 `pytest algorithm` 退出码 0；证据：命令输出。
  - `rule` TR-14.2: T01~T15 共 15 条场景用例可被 `-k` 逐一点名，断言覆盖 FR-20 全部特殊点（T05/T09 clarify、T10/T15 not_answerable、T06 AOV 分母、T07 三段+changes、T08 yoy、T14 limit=3）；证据：pytest 列表与输出。
  - `rule` TR-14.3: 专项路径测试全部存在且通过（命中/降级/超轮/超时/不可用/空结果/两轮/重入/无 key/边界扫描）；证据：pytest 输出。
  - `rubric` TR-14.4: 场景业务保真度（AC-16 同维）；threshold >= 4；证据：fixture 与测例.md/metrics-dictionary 逐条走读。
  - `rubric` TR-14.5: 可替换性/可维护性（AC-17 同维）；threshold >= 4；证据：仅替换 deps 中协议实现即可切「半真实」装配的走查记录（不实际连库）。

## Task 15: 中段入口（S5 刷新 / S4 recalibrate）【增补】
- **Status**: `done`（pytest 46 用例全绿：既有 34 回归 + 本任务 12 新增）
- **Priority**: high
- **Depends On**: Task 1~14（已交付）
- **Description**:
  - `graph.py` 扩展 `run_chain` 签名：新增可选参数 `query_spec`（QuerySpec）与 `start_at`（`None`｜`"S4"`｜`"S5"`，默认 `None`=主入口，行为与既有 34 用例完全一致）；中段入口时 input_state 以重置字段为底、注入 query_spec 与入口标记，入口路由直达 S4/S5。
  - S4 节点 recalibrate 分支：状态带 recalibrate 标记时不调 LLM 对齐，直接构造逐项重选 clarify 卡（options 来自 L0 层级/枚举候选；缺时间项附 time_quick；round=1、reason_code=METRIC_DIM_AMBIGUOUS）；全程不执行 SQL、不触碰 QueryRunner。
  - S5 刷新路径：入口态 RetrievalContext 为空，Coder 仅按 QuerySpec + L0 生成；lint 白名单照 L0；S6~S8 与主链共用同一套节点与终态组装（零复制）。
  - 不改动 ChainResult/六 action/载荷结构（后端与前端镜像契约保持不变）。
- **Acceptance Criteria Addressed**: AC-18, AC-19
- **Test Requirements**:
  - `rule` TR-15.1: start_at="S5" 四分支：answer（断言 path=S5,S6,S7,S8 且不含 S1~S4）、空结果 answer(rows=[],chart=null)、query_gen_failed（超轮）、query_failed（超时/异常）；证据：单测。
  - `rule` TR-15.2: start_at="S5" 且带 ComparisonSpec 的 QuerySpec → grouped_bar/trend_line + changes 正确（与主链 T07 同构断言）；证据：单测。
  - `rule` TR-15.3: start_at="S4" → MockQueryRunner 调用=0、clarify 卡 round=1、reason_code=METRIC_DIM_AMBIGUOUS、options 逐项可重选、无 L1 时照常出卡；证据：单测。
  - `rule` TR-15.4: recalibrate 确认后带 clarified_question+clarify_id 从 S1 重入直达终态（复用既有重入测试机制）；证据：单测。
  - `rule` TR-15.5: 不带新参数调用 run_chain 的全部既有用例回归通过（pytest 全绿、无行为漂移）；证据：全量 pytest 输出。
