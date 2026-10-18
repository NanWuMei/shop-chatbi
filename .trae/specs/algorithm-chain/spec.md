# 算法问数链路（algorithm-chain）- 需求规格

## Overview
- **Summary**：在仓库根新建 `algorithm/` Python 包，落地 `docs/SDD-算法应用.md` v0.4 的 8 步问数链路（S1 understand → S2 template_match → S3 retrieve → S4 align → S5 gen_sql → S6 execute → S7 build_view → S8 insight），以 LangGraph（StateGraph + Coder 子图 + checkpointer）编排，对外唯一入口为 `run_chain`，唯一返回契约为 `ChainResult`。
- **状态**：Task 1~15 已全部交付（pytest 46 用例全绿，含两中段入口与 ChainResult service-only 字段）；后端步可开工。
- **Purpose**：这是 P5 三轮 `/spec` 的第一步（算法 → 后端 → 前端）。算法链路是全系统的问数内核；本步交付可离线回归的内核，后端步再注入真实 QueryRunner/资源/连接，前端步只消费 ChainResult。
- **Target Users**：后端服务（调用方，后续步骤）、评测 runner（直接调 `graph.ainvoke()` 跑 T01~T15）；不直接面向终端用户。

## Goals
- 8 步链路与 SDD §1 流程图逐节点对应：四个 LLM 智能体（Understand/Aligner/Coder/Writer）+ 四个规则/工具节点（TemplateMatcher/Retriever/Executor/Presenter），路由只按状态显式字段（`template_hit` / `lint_passed` / `action`）。
- `ChainResult` 与 SDD §6 逐字段一致，六种 action（answer / clarify / not_answerable / query_gen_failed / query_failed / error）全部可达。
- 「无字典也能跑」：L0 库结构是唯一必需上下文；L1 字典、S2 模板、exemplar、Embedding 全部可选，缺失逐项降级且 T01~T15 期望结果不变。
- 算法不直连库：执行只经注入的 `QueryRunner` 协议；本步用 Mock 实现，T01~T15 全链路离线回归（mock LLM + MockQueryRunner），不依赖网络、API key、数据库服务。
- 双档模型（Understand/Writer=fast、Aligner/Coder=strong）走 OpenAI 兼容 env 配置，无 key 时 import/构建不报错，仅问数时出 error。
- 目录结构与 SDD §5 模块树一致。

## Non-Goals
- **不做真连库**：不建立任何真实数据库连接、不要求 DB 服务在线；不实现 pgvector 的真实 SQL 执行（exemplar 表由后端迁移建、Repository 的 psycopg+pgvector 实现归后端步）。
- **不做真 information_schema 抽取的在线 Provider**：本步只交付 Provider 协议 +「抽取结果行→SchemaBlock」解析器 + 静态快照实现；真实抽取 Provider 归后端步装配。
- 不做 HTTP/SSE、会话与消息落库、报表快照、任何页面。
- 不正式产出第一包业务资源（L1 metrics/category/time-calendar YAML、S2 业务模板、exemplar seed）——那是数据步（P6）产出；测试 fixtures 中的临时资源仅用于覆盖增强/降级路径。
- 不做自由 agent swarm（唯一自治是 Coder 自环 ≤2 轮）、多模型自动路由（仅 fast/strong 两档）、归因/预测、跨源。
- 不修改 `docs/` 任何文件；不创建 `algorithm/` 与 `.trae/specs/` 之外的代码目录。

## Background & Context
- 权威输入：`docs/SDD-算法应用.md` v0.4（链路、状态、契约、存储、模型、编排）；总览只当地图，冲突以算法 SDD 为准。
- 回归集：`docs/测例.md` T01~T15（SDD §10 给定每条测例的链路落点与出口）。
- L0 静态快照依据：`docs/metrics-dictionary.md` §5 六张 dw 表（dim_date / dim_channel / dim_category / fact_order / fact_order_item / fact_traffic_daily）、§2 四指标口径、§4.1 档期区间。
- 仓库当前零业务代码；硬规则（`.trae/rules/project_rules.md`）：算法 LangGraph 进程内嵌、算法不直连库、无字典也要能跑、不另设计向量存储。
- 上下游约定（本步只预留口，不实现）：后端在 application 层调 `run_chain` 并注入 QueryRunner/LLM/Embedding/SchemaProvider/Repository/resources 路径；过程状态经节点事件回调由后端映射 SSE 三 stage。

## Functional Requirements

### 链路与编排
- **FR-1**：`build_graph(...)` 产出编译后的 LangGraph 主图，节点注册与顺序为 S1→S2→(命中跳 S6 | 未命中 S3)→S4→S5(子图)→S6→S7→S8；所有分叉按 ChainState 显式枚举/布尔字段路由，不解析自然语言。
- **FR-2**：S5 Coder 为编译子图，内含 gen→lint→（不过带 lint 报错回 gen）回边，自环最多 2 轮；超轮置 `query_gen_failed(GEN_LINT_EXHAUSTED)`。
- **FR-3**：澄清重入从 S1 进入（`clarified_question`），由 checkpointer 恢复既有槽位；`round` 取 1|2，两轮后用户仍未消歧则转 `not_answerable`。
- **FR-4**：`run_chain` 为 async 入口（LangGraph `ainvoke` 语义），支持 question / clarified_question 输入、thread/checkpointer 会话标识、可选 `on_event` 节点回调；回调只发节点级与终态事件（node_started/node_finished/terminal），不含 HTTP/SSE 语义。
- **FR-5**：评测可直接以依赖注入方式装配 mock LLM、mock embedding、静态 L0、内存 Repository、MockQueryRunner 后跑完整链路（SDD §5 边界铁律 5：不经 HTTP）。

### 各节点行为
- **FR-6（S1）**：Understand 输出 `IntentSpec`（指标/维度/时间窗/对比意图/过滤/排序/TopN/槽位形态）；闲聊、归因、预测类当场 `not_answerable(NOT_DATA_QUESTION)`；LLM 异常重试 1 次后 `error(E_LLM_UNAVAILABLE, retryable=true)`。
- **FR-7（S2）**：纯规则匹配 YAML 模板库（不调 LLM）：槽位填满且无模板外新约束才 `hit=true`，直跳 S6；模板库为空/无匹配/抽不齐/有新约束一律未命中走 S3，不算失败；命中结果含 template_id、已填 SQL、chart_type、bindings。
- **FR-8（S3）**：Retriever 输出 `RetrievalContext{schema_blocks[], caliber_defs[], entity_defs[], exemplars[], mode}`：L0 schema_blocks 必有；L1 口径/实体与 exemplars 有则返回 top3~5；embedding 未配置或调用失败 → 纯关键词通道且 `mode=lexical`（trace 标注）；L0 为空时返回空上下文不报错。检索结果只作 S4/S5 输入上下文，不做事后比对、不作授权。
- **FR-9（S4）**：Aligner 输出 `QuerySpec`（指标→表/列/聚合/口径过滤；维度→列；时间→绝对日期；实体展开；排序/limit）+ 可选 `ComparisonSpec`；出口：多候选（L0 层级/枚举采样即可触发）→ `clarify(METRIC_DIM_AMBIGUOUS)`；无任何可对应表/列 → `not_answerable(NO_MATCHING_DATA)`；口径自相矛盾（如类目粒度转化率）→ `not_answerable(CALIBER_CONFLICT)`；缺时间且无法默认 → `clarify(MISSING_TIME)`；指代消解失败 → `clarify(ANAPHORA_UNRESOLVED)`；问法过泛 → `clarify(VAGUE)`。无 L1 时依 L0 列名/注释对齐，口径必须在 caliber 中明示，不因缺字典拒答。
- **FR-10（S5）**：Coder 输入 QuerySpec+RetrievalContext 输出 `sql`+`lineage`（表/列/口径/exemplar_ids）；lint 为纯规则：① 表/列白名单按本次 L0；② 仅允许单条 SELECT（禁写/多语句/DDL/DML 一刀切拒绝）；③ 列归属校验；④ 自动注入 LIMIT（默认 500、上限 1000，参数可注入）。示例中的表不构成授权。Coder 不持有任何执行工具。
- **FR-11（S6）**：Executor 只调注入的 `QueryRunner.run(sql) -> QueryResult{columns, rows, row_count, truncated}`；超时 → `query_failed(QUERY_TIMEOUT)`；执行异常 → `query_failed(QUERY_ERROR)`；0 行如实返回，继续 S7/S8，不是拒答。
- **FR-12（S7）**：Presenter 纯规则（不调 LLM），按 QuerySpec 形态对照出图：排名/TopN→`bar`；时间趋势→`line`/`trend_line`；对比→`grouped_bar`/`trend_line`；占比→`pie`；单标量或空结果→`chart=null`。`TableData{columns:[{field,label,format}], rows, truncated, display_limit}` 始终产出；ChartSpec 含 `{type, x_field, series:[{field,label}], switchable[]}`。对比模式下变化值/变化率由代码用 Decimal 计算：金额 2 位小数、率 1 位小数；某时段 0 行/分母为 0 → `rate_delta=null`（不可比），严禁编造无穷大。
- **FR-13（S8）**：Writer 只看真实行+口径+ChartSpec+代码算好的对比值（拿不到 SQL、拿不到库），输出严格一句中文 `insight`；只陈述事实，不给建议/不归因/不预测；数字落地校验（抽取句中数字逐一核对来自真实行或对比值，容忍格式化误差）失败→重生成 1 次→仍失败用规则模板句兜底并在 trace 标注；**解读失败永不阻断 answer**。空结果固定输出「该范围无数据」语义句。
- **FR-14（clarify 载荷）**：`{clarify_id, round(1|2), title, reason_code(4 码), input_type(single_choice|time_quick|question_suggestions), options:[{value,label}], suggestions:[{question}], allow_custom_text:true}`；确认前不出任何数字。

### 契约
- **FR-15**：`ChainResult` 顶层为 `action` + 恰好一个非空载荷（answer?/clarify?/rejection?/error?）+ `trace{path[], template_hit, retrieval_mode, lint_rounds, llm_calls, elapsed_ms}` + `meta{turn_id, question}`；rejection 六 reason_code 与 SDD §6 完全一致，reason_text 为业务大白话且不含 SQL/堆栈/技术码，suggestions 为可点击问法；answer 载荷含 `{table, chart, insight, caliber:{summary, detail:{metrics,dimensions,time_range,filters,comparison?}}, comparison?{mode,periods[],changes:[{key,value_delta,rate_delta|null}]}}`；空结果＝answer（rows=[]、chart=null、caliber 照给）。

### 模型与资源
- **FR-16**：LLMClient 为 OpenAI 兼容 chat completions + 结构化输出抽象；env：`LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`（默认）+ `LLM_MODEL_FAST/LLM_MODEL_STRONG`（缺省回落默认）+ `LLM_TIMEOUT_SECONDS`（默认 30）；registry 按 SDD §5 表把节点映射到档位；客户端工厂延迟构建，无 key 时包可正常 import、图可正常 build。代码中不出现厂商名。
- **FR-17**：EmbeddingClient 为 OpenAI 兼容抽象，env：`EMB_BASE_URL/EMB_API_KEY/EMB_MODEL/EMB_DIM`；未配置/失败时 S3 降级 lexical；embed 结果带进程内短缓存（同文本 5 分钟）。
- **FR-18**：资源加载器从可注入路径读 L1 dict YAML 与 S2 templates YAML，启动加载；路径不存在或目录为空时视为「无增强」，不报错。Writer 的 `style_examples.yaml` 为包内自带文件（控格式，不供数字）。
- **FR-19**：`Repository` 协议（`search_exemplars / upsert_exemplar / load_schema_cache`）与 `QueryRunner`、`SchemaProvider` 协议在算法包内定义；本步提供内存/静态/mock 实现，真实实现留给后端步，切换不动链路代码。

### 回归
- **FR-20**：pytest 离线回归覆盖 T01~T15：每条断言 `action`、图型（或 chart=null）、关键口径字段；T05/T09 断言 clarify 及 reason_code/round；T10/T15 断言 not_answerable 及 reason_code；T06 断言 caliber 明示 AOV 分母；T07 断言 3 段 periods 与 Decimal changes；T08 断言 yoy；T14 断言 limit=3；并覆盖 S2 命中/未命中两条路径、lexical 降级、lint 回炉与超轮、query 超时/报错、LLM 不可用、空结果、澄清两轮转拒答、checkpointer 重入。

### 中段入口（增补；后端 SDD §3.2③/§3.4 的硬依赖）
- **FR-21（S5 刷新入口）**：`run_chain(..., query_spec=<QuerySpec>, start_at="S5")`——接受一份已确认的 QuerySpec（含 ComparisonSpec）从 S5 起跑（gen_sql→lint 自环→S6 执行→S7 出表图→S8 解读），**不跑 S1~S4、不产出 clarify**；入口态 RetrievalContext 为空，Coder 仅按 QuerySpec + L0 生成（lint 白名单照 L0）；返回 action ∈ answer / query_gen_failed / query_failed / error，0 行为空 answer（rows=[]、chart=null），与主链终态完全同构；trace.path 断言不含 S1~S4。
- **FR-22（S4 recalibrate 入口）**：`run_chain(..., query_spec=<QuerySpec>, start_at="S4")`——对「口径不对，重新澄清」场景：不重新理解/检索/对齐，S4 节点走 recalibrate 分支**强制产出 clarify 卡**（对原指标/维度/筛选项逐项给重选入口：options 按 L0 层级/枚举候选构造；原规格缺时间项时附 time_quick；`round=1`、`reason_code=METRIC_DIM_AMBIGUOUS`——复用现有四码不扩枚举），**不执行 SQL**（QueryRunner 调用=0）；用户确认后按既有主链路 `clarified_question + clarify_id` 从 S1 重入，两轮上限不变。

## Non-Functional Requirements
- **NFR-1（离线）**：全部测试在无网络、无任何 LLM/EMB key、无数据库进程的条件下通过；CI 不依赖商用 API。
- **NFR-2（可维护性）**：四智能体各自独立目录（node/prompts/schemas 分离），节点间只传 ChainState 强类型字段（pydantic/dataclass），无自然语言中间态；公共契约集中在 `state.py`。
- **NFR-3（Python 基线）**：Python 3.12；async 入口；依赖锁定在 `algorithm/requirements.txt`；测试依赖单独声明（pytest / pytest-asyncio）。
- **NFR-4（可观测）**：trace 字段全程累积（path、template_hit、retrieval_mode、lint_rounds、llm_calls、elapsed_ms），只供评测排查，不进面向用户文案。
- **NFR-5（数值正确性）**：金额/率/对比计算全部 Decimal，禁止浮点直算业务数字。

## Constraints
- **Technical**：LangGraph StateGraph + compiled Coder 子图 + checkpointer（离线用内存 checkpointer）；LangChain 做模型/结构化输出抽象；OpenAI 兼容协议；不引入向量库/数据库服务。
- **Business**：以已接入库（L0 六表）为可答边界；指标唯四、档期区间、美妆多候选、数据覆盖以 metrics-dictionary 为准；归因/预测不答。
- **Dependencies**：本步只依赖 docs 与本地 Python 环境；后端/前端不存在，所有外部能力以协议 + mock 落地。
- **相对 SDD 的一处工程细化（需审批确认）**：SDD §5 的 requirements 只列了 `langgraph / langchain / langchain-openai / psycopg[binary]`。FR-10 的 lint 要做可靠的表白名单/禁写/列归属校验，正则易被绕过（注释、多语句、CTE 嵌套），拟新增纯 Python 依赖 **sqlglot** 做 SQL AST 解析（无原生依赖、不需数据库）；psycopg 按 SDD 写入 requirements 但本步代码不 import（真连接归后端步）。若不接受 sqlglot，则退回 sqlparse + 手写规则并在评审中重估 lint 强度。

## Assumptions
- 包根为仓库根下 `algorithm/`（SDD §5 模块树）；测试置于 `algorithm/tests/`，fixtures（L0 六表静态快照、各测例行数据、T01~T15 mock 脚本与期望、临时 L1/模板资源）置于 `algorithm/tests/fixtures/`。
- L0 静态快照按 metrics-dictionary §5 的表/字段大纲与「中文列注释 + 中文枚举值」硬要求构建；美妆多候选（美妆个护/彩妆/护肤/美妆工具）必须真实出现在快照枚举中以支撑 T05/T09。
- mock LLM 以「场景脚本」方式按节点返回 canned 结构化输出；MockQueryRunner 按 fixture 返回行；回归不断言 SQL 文本相等，而断言 lineage 引用表/列 ∈ L0、lint 通过、终态与图型/口径字段符合期望。
- 节点事件回调只定义机制（on_event），SSE stage 映射归后端步。
- 本步完成后 `algorithm/` 不被任何 HTTP 服务引用；后端步再做装配。

## Acceptance Criteria

### AC-1: 八步主链路与显式路由
- **Type**: `rule`
- **Given**: 装配齐全 mock 依赖的链路与一个普通取数问题（T01）
- **When**: 调 `run_chain`
- **Then**: trace.path 依次经过 S1/S3/S4/S5/S6/S7/S8（S2 未命中）或命中时 S1/S2/S6/S7/S8；无任何由自然语言判断驱动的分叉
- **Pass Condition**: 有测试断言两种 path 形状分别与 SDD §1 一致，且路由函数只读取状态字段
- **Evidence**: `pytest` 对应测试输出 + graph.py 条件边代码

### AC-2: ChainResult 契约逐字段
- **Type**: `rule`
- **Given**: SDD §6 的 ChainResult 字段清单
- **When**: 审查 `state.py` 中 ChainResult 及载荷模型
- **Then**: action 六值、answer/clarify/rejection/error/trace/meta 各字段名、嵌套结构、可空性（chart 可 null、rate_delta 可 null、载荷互斥）与 SDD 完全一致
- **Pass Condition**: 逐字段对照表通过；有测试验证「恰好一个载荷非空」「空结果＝answer+rows=[]+chart=null」
- **Evidence**: 模型定义代码 + 契约单测

### AC-3: S1 非数据问题与模型故障出口
- **Type**: `rule`
- **Given**: T15 类归因问法；以及一个持续抛错的 mock LLM
- **When**: run_chain
- **Then**: 归因 → `action=not_answerable, reason_code=NOT_DATA_QUESTION`，reason_text 为「不算原因、可给相关数据」语义且附 suggestions；LLM 失败在节点内重试 1 次后 → `action=error, code=E_LLM_UNAVAILABLE, retryable=true`
- **Pass Condition**: 两出口均有测试断言 action/reason_code/重试次数（trace.llm_calls 体现）
- **Evidence**: S1 节点测试

### AC-4: S2 模板快路径为可选皮肤
- **Type**: `rule`
- **Given**: ① resources 路径为空；② 注入含 1 条可填满模板的场景；③ 槽位抽不齐/含模板外新约束
- **When**: 分别经过 S2
- **Then**: ①③ 未命中且无 error，继续 S3；② hit=true 并跳过 S3/S4/S5 直抵 S6，trace.template_hit=true
- **Pass Condition**: 三种情况各有测试；空目录场景下全链路 T01~T15 默认跑主路径
- **Evidence**: template_match 单测 + 场景回归

### AC-5: S3 双通道与 embedding 降级
- **Type**: `rule`
- **Given**: ① 未配置 EMB_*；② 配置但 embedding 客户端调用抛错；③ 正常 mock embedding
- **When**: S3 检索
- **Then**: ①② mode=lexical 且 trace 标注、不抛错；③ mode=vector 并返回 exemplar top3~5；三种情况下 schema_blocks 恒非空（L0 静态快照存在时），L0 为空时返回空上下文且后续不崩
- **Pass Condition**: 四种条件有测试；检索结果对象只被 S4/S5 作为上下文读取
- **Evidence**: retrieve/lexical/vector 单测

### AC-6: S4 三拒答/澄清出口与无字典对齐
- **Type**: `rule`
- **Given**: T09/T05（美妆多候选）、缺时间问法、指代消解失败、T10（无对应表列）、类目粒度转化率、无任何 L1 资源的普通取数
- **When**: S4
- **Then**: 分别产出 clarify(METRIC_DIM_AMBIGUOUS/MISSING_TIME/ANAPHORA_UNRESOLVED)、not_answerable(NO_MATCHING_DATA)、not_answerable(CALIBER_CONFLICT，且 suggestions 引导渠道口径)；无 L1 场景正常产出 QuerySpec 且 caliber 明示推断口径（T06 明示 AOV 分母＝支付订单数）
- **Pass Condition**: 每出口 ≥1 测试；澄清 options 来自 L0 层级/枚举候选，不依赖 L1 文件
- **Evidence**: aligner 节点测试 + T05/T06/T09/T10 场景

### AC-7: S5 lint 四规则与超轮拒答
- **Type**: `rule`
- **Given**: ① 合规 SELECT；② 含 DROP/多语句/非 SELECT；③ 引用 L0 白名单外表或不存在列；④ 无 LIMIT 查询；⑤ 连续 2 轮 lint 失败的 mock Coder
- **When**: Coder 子图运行
- **Then**: ②③ 判不通过并把具体原因回传 gen；④ 自动注入 LIMIT（≤1000）后通过；⑤ lint_rounds=2 后终止为 `query_gen_failed(GEN_LINT_EXHAUSTED)`，rejection 带 lint 原因
- **Pass Condition**: 五类各有测试；通过的 SQL 其 lineage 表/列全部 ∈ L0
- **Evidence**: coder/lint 单测

### AC-8: S6 执行边界与空结果
- **Type**: `rule`
- **Given**: MockQueryRunner 的三种脚本：正常多行、返回 0 行、超时、抛执行异常
- **When**: S6
- **Then**: 正常→继续；0 行→action 最终为 answer（rows=[]、chart=null、「该范围无数据」语义 insight）；超时→query_failed(QUERY_TIMEOUT)；异常→query_failed(QUERY_ERROR)；算法包内 grep 不到任何真实数据库驱动连接调用（psycopg 不被 import）
- **Pass Condition**: 四种结果测试 + 依赖扫描检查
- **Evidence**: execute 节点测试 + 静态检查输出

### AC-9: S7 图型映射与表结构
- **Type**: `rule`
- **Given**: 排名、日趋势、对比、占比、单标量、空结果六类 QuerySpec+QueryResult
- **When**: build_view
- **Then**: 图型分别为 bar / trend_line(或 line) / grouped_bar|trend_line / pie / null / null；TableData 四字段（columns 含 field/label/format、rows、truncated、display_limit）齐备；ChartSpec 字段齐备
- **Pass Condition**: 六类各有断言（含 T01/T03/T07/T13/T06）
- **Evidence**: build_view 单测

### AC-10: 对比 Decimal 计算
- **Type**: `rule`
- **Given**: T07 三段、T08 同比两段的 QueryResult（含某段 0 行）
- **When**: S7 计算 changes
- **Then**: value_delta 金额 2 位、rate_delta 率 1 位；分母 0 的段 rate_delta=null；全部由代码计算（Writer 输入不含需其推算的数值）
- **Pass Condition**: 断言精度、舍入与 null；代码检查无 float 参与业务运算
- **Evidence**: comparison 计算单测

### AC-11: S8 一句解读与数字落地兜底
- **Type**: `rule`
- **Given**: 正常行；Writer 吐出含行外数字的句子（mock）；Writer 持续不合规；空结果；对比结果
- **When**: S8
- **Then**: 正常→一句、数字均可在真实行/changes 中找到；不合规→重生成 1 次→再失败用模板句（trace 标注）且 action 仍为 answer；空结果→「该范围无数据」语义；对比句只陈述方向幅度；所有 insight 无建议/归因/预测措辞
- **Pass Condition**: 各分支测试 + 数字抽取核对器单测
- **Evidence**: writer 节点测试

### AC-12: 澄清票据、两轮上限与 checkpointer 重入
- **Type**: `rule`
- **Given**: T09 首轮澄清→用户选择→重入；以及连续两轮选择后仍无法消歧的脚本
- **When**: 带 thread 标识两次调 run_chain（第二次带 clarified_question + clarify_id）
- **Then**: 首轮确认前无 SQL 执行（MockQueryRunner 调用次数=0）且载荷满足 FR-14；重入恢复槽位并直达出数；两轮后转 not_answerable
- **Pass Condition**: 场景测试断言轮次、MockQueryRunner 调用计数与终态
- **Evidence**: T09 场景 + checkpointer 测试

### AC-13: 双档模型与无 key 可启动
- **Type**: `rule`
- **Given**: env 分别配置/缺省 LLM_MODEL_FAST、STRONG；以及完全不设 key
- **When**: registry 解析档位；import 包并 build_graph；随后发起问数
- **Then**: Understand/Writer 取 fast、Aligner/Coder 取 strong，缺省回落 LLM_MODEL；无 key 时 import/build 不抛错，问数时走 error(E_LLM_UNAVAILABLE)；代码内无厂商名字面量
- **Pass Condition**: registry 单测 + 无 key 装配测试 + grep 检查
- **Evidence**: llm/registry、client 测试

### AC-14: 模块树与边界铁律
- **Type**: `rule`
- **Given**: SDD §5 模块树与四条边界铁律
- **When**: 审查交付目录
- **Then**: 目录/文件与模块树一一对应；Coder 模块不 import execute/QueryRunner；Writer/Presenter 不 import SQL 执行与连接；Understand 不做表/列授权判断；节点交接只使用 state.py 强类型
- **Pass Condition**: 目录 diff + import 边界静态检查
- **Evidence**: 仓库树 + 检查脚本输出

### AC-15: T01~T15 离线回归全绿
- **Type**: `rule`
- **Given**: 干净环境（无网络/无 key/无 DB）
- **When**: 运行 `pytest`
- **Then**: T01~T15 每条场景按 SDD §10 断言 action、图型/chart、关键口径、reason_code（T05/T09/T10/T15 特殊断言见 FR-20），全部通过
- **Pass Condition**: 测试进程退出码 0 且 15 条场景用例齐全可点名
- **Evidence**: pytest 汇总输出

### AC-16: 回归场景的业务保真度
- **Type**: `rubric`
- **Dimension**: fixtures 与 mock 脚本对测例业务语义的还原程度（档期区间、美妆多候选、数据故事方向、口径文案）
- **Scale**: 1-5
- **Anchors**: 1 = 场景只有占位数据、无法对应测例文字；3 = 主路径可跑但时间/枚举/口径与 metrics-dictionary 有出入；5 = 15 条场景的输入文案、L0 枚举、行数据方向、期望口径全部能与测例.md/metrics-dictionary 逐条对照
- **Pass Threshold**: >= 4
- **Evidence**: fixtures 目录与场景 yaml 评审、抽测人工走读

### AC-17: 内核代码可维护性
- **Type**: `rubric`
- **Dimension**: 节点/智能体隔离与可替换性（协议注入、提示词独立、无硬编码场景分支）
- **Scale**: 1-5
- **Anchors**: 1 = 链路里写死测例 if/else 才能跑通；3 = 主结构清晰但个别节点耦合 mock 细节；5 = 生产实现只需按协议注入即可替换全部 mock，提示词/schema/节点三者分离，新增一个 LLM 节点不改路由骨架
- **Pass Threshold**: >= 4
- **Evidence**: 代码走读 + 依赖注入装配处评审

### AC-18: S5 刷新入口（增补）
- **Type**: `rule`
- **Given**: 一份已确认的 QuerySpec（含/不含 ComparisonSpec）+ 脚本化 Coder 与 MockQueryRunner
- **When**: `run_chain(query_spec=..., start_at="S5")`
- **Then**: trace.path = S5→S6→S7→S8（不含 S1~S4）；成功 → answer；lint 两轮不过 → query_gen_failed(GEN_LINT_EXHAUSTED)；Runner 超时/异常 → query_failed；0 行 → 空 answer；全程无 clarify、载荷与主链同构
- **Pass Condition**: 四分支各有单测并断言 path 与载荷
- **Evidence**: 单测输出

### AC-19: S4 recalibrate 入口（增补）
- **Type**: `rule`
- **Given**: source turn 落库的 QuerySpec
- **When**: `run_chain(query_spec=..., start_at="S4")`
- **Then**: 强制 clarify（round=1、reason_code=METRIC_DIM_AMBIGUOUS、options 按 L0 候选逐项重选、缺时间项附 time_quick）；MockQueryRunner 调用次数=0；确认后带 clarified_question+clarify_id 从 S1 重入并直达终态
- **Pass Condition**: 单测断言载荷字段、调用计数与重入入参
- **Evidence**: 单测输出

## Resolved Decisions（已批准，取代原 Open Questions）
- **OQ-1**：同意 lint 引入 **sqlglot**（已随主链实现落地，lint 四规则以其 AST 校验实现）。
- **OQ-2**：requirements 保留 psycopg[binary] 但本步不 import（默认结论，主链已照此交付）。
- **OQ-3**：`algorithm/resources/` 默认留空，业务 YAML 归 P6（默认结论，主链已照此交付）。
- **OQ-4**（后端评审增补，已批准）：`ChainResult` 增补两个**仅服务端字段** `query_spec`（本次对齐产出的 QuerySpec）与 `sql`（S5 生成、S6 执行的 SQL）——后端 internal 三键落库（{sql,trace,query_spec}）、报表保存/刷新/recalibrate 的唯一数据来源；禁止出现在任何前端报文，前端 TS 镜像不含。对应 SDD-算法应用 §6 已同步；实现落在 state.py/graph.py，断言随 Task 15 测试补齐。
