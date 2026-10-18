# 09 · 本地部署与测例跑通 Prompt

连库一律用 Supabase Transaction 池化（`*.pooler.supabase.com:6543`）。免费档直连 5432 不可用，不要再向用户要直连、不要为此改去开会员或起本地 Postgres。本项目没有 alembic（app 表启动 create_all 自动建），也没有 MOCK / CLARIFY 开关（无 LLM key 服务照常启动，问数才报 E_LLM_UNAVAILABLE）。

---

## 第 1 轮 · 本机进程能起来，先别问业务题

```
前端、后端、算法代码都已完成。现在只把本机开发进程拉起来，连上已有的 Supabase（07 已导入 dw 业务数据），不要 Compose、不要打镜像、不要改 dw schema、不要改 L1 YAML、不要跑测例问句。

先读：
- backend_service/.env.example
- backend_service/config.py（APP_/ANALYTICS_DATABASE_URL 双连接串、APP_SCHEMA/DW_SCHEMA）
- web/src/api/client.ts（API_BASE=/api/v1 相对路径）与 web/vite.config.ts（/api 代理样例被注释着）
- docs/SDD-后端.md 第 4.1、5.1 节（app/dw 双 schema、双引擎）

请先向我要这些（缺一就停，不要猜、不要用仓库里可能残留的密码）：
- 与 07 同一套 **Transaction 池化**连接串（Host=*.pooler.supabase.com，端口 6543，用户多为 postgres.<project-ref>，sslmode=require）。已拍板：APP_DATABASE_URL 与 ANALYTICS_DATABASE_URL 都填这同一条 postgresql:// 串。不要要 5432 直连。
本轮不要问 LLM、不要问 Embedding。

然后做：
1. 从 backend_service/.env.example 复制出本机 backend_service/.env（不要提交 .env）
2. 填 APP_DATABASE_URL、ANALYTICS_DATABASE_URL（同一条 Transaction 串，带 sslmode=require）、APP_SCHEMA=app、DW_SCHEMA=dw、RESOURCES_PATH 指到 algorithm/resources（本机相对路径）。LLM/EMB 留空：无 key 服务照常启动，问数才报 E_LLM_UNAVAILABLE，属预期
3. 安装依赖：backend_service 按 requirements.txt；web 若缺 node_modules 再 npm install。工作目录不要搞错
4. Transaction 模式不支持预处理语句：若启动或建表报 DuplicatePreparedStatement 或类似错误，允许只改 backend_service/data/engines.py，两个引擎都加 prepare_threshold=0（app 引擎 connect_args、analytics 引擎 psycopg.connect 参数）。不要改回直连，不要起本地 Postgres
5. 在 Supabase 幂等执行一次初始化 SQL（08 轮若已建过 app schema 与 vector 扩展就只剩补缺）：CREATE EXTENSION IF NOT EXISTS vector; CREATE SCHEMA IF NOT EXISTS app; CREATE SCHEMA IF NOT EXISTS dw;。app 下的会话/消息/报表表不用手工建——后端启动 create_all 幂等自建，本项目没有 alembic，不要去装
6. 起后端：仓库根目录 uvicorn backend_service.main:app --reload --port 8000 --env-file backend_service/.env（代码不自动读 .env，必须 --env-file 或手工 export；从仓库根跑不需要再设 PYTHONPATH）
7. 起前端：web 下 npm run dev，并把 vite.config.ts 里注释的 /api 代理打开（target http://localhost:8000，属允许的接线修改）。浏览器走 [http://localhost:5173](http://localhost:5173)，不要直接打 8000 当页面
8. 用 GET [http://localhost:5173/api/v1/health](http://localhost:5173/api/v1/health)（或直打 8000 同路径）看检查项：db 必须 ok；llm/embedding=unconfigured（整体 degraded）可以

若连不上库或启动失败：把报错原文给我，指出是凭据、6543、ssl 还是 app schema 权限，不要改去起 Compose、本地 Postgres，或让用户开通直连会员。

交付：
- 本机怎么起两个进程（命令、工作目录、--env-file）
- health 原文
- .env 里填了哪些变量名（不要贴密码）
- 确认 dw 业务表仍在、app 下只新增会话/消息/报表等应用表
```

**人审**：有没有又起了 Compose；连的是不是 6543 池化、两个 URL 是不是同一条串；密码有没有进 git；有没有顺手装 alembic。

---

## 第 2 轮 · 切到真链路，先跑通一句问数

```
第 1 轮进程已经起来。现在切真 LLM（+可选 Embedding），先在界面上问通一句，不要一次跑完 T01-T15，不要 Compose。

请先向我要（缺一就停）：
- 问数 LLM 三元组：LLM_BASE_URL、LLM_API_KEY、LLM_MODEL（OpenAI 兼容即可；LLM_MODEL_FAST/STRONG 可选）
- Embedding：EMB_BASE_URL / EMB_API_KEY / EMB_MODEL / EMB_DIM（维度确认是否 1024）。若用户说这轮先不配，检索走 lexical 降级，继续问数，不要卡死

然后做：
1. 改 backend_service/.env：填 LLM；有 Embedding 就填 EMB_*，没有就留空（本项目没有 MOCK_MODE，不存在「关 Mock」这步）
2. 重启后端，再打 /api/v1/health：db 与 llm 都应 ok（整体 status=ok；EMB 未配不挡）
3. 打开 [http://localhost:5173](http://localhost:5173)，在对话页用自然语言问一句简单的（用 T01 原句「618大促期间各渠道GMV是多少，按从高到低排」）
4. 确认：SSE 流走 stage 帧后出 answer 终态（表+解读），不是编造假数；结果来自 dw schema；页面有表或解读，而不是一直转圈或 error/rejection
5. 若失败：根据 SSE 终态帧 / 后端日志判断是 L0 仍空、连错库、LLM 调用失败还是执行超时。把日志关键段给我。不要为了出数去改 07 的表或编 SQL 塞进前端

交付：health 原文、这一句问的原文、页面终态（answer/rejection/error）、是否像真库结果。不要贴 API Key。
```

**人审**：问的是页面而不是 curl 一篇 SQL；EMB 未配时是否走 lexical 降级而不是卡死；有没有把密钥写进文档。

---

## 第 3 轮 · 在界面上按测例把问数调试通

```
真链路已经能问出一句。现在按 docs/测例.md 在 [http://localhost:5173](http://localhost:5173) 对话页逐条用自然语言问 T01-T15，把问数调试通。不要手写测例答案 SQL，不要 Compose，不要重做种子。

澄清是链路内建行为，没有开关，不要去找 CLARIFY_ENABLED。

怎么算这条过（按当前 docs/测例.md 的编号与含义）：
- T01：answer，有表，渠道 GMV 能从高到低排
- T02：answer，有柱状图（渠道转化率；图型不对属界面问题可修）
- T03：answer，有趋势图，6/16-6/18 分日
- T04：answer，有表，退货率 Top3 类目
- T05：answer，有一句解读，「美妆」退货率相对 8% 阈值方向明确
- T06：answer，表+解读，AOV 数值正确，口径摘要里明示分母（订单数或付款人数）
- T07：answer，柱状图+表，前一周 / 正式期 / 后一周 GMV 环比
- T08：answer，表+解读，今年 vs 去年 618 整体 GMV 涨跌与差额
- T09：优先看到 clarification（「美妆」多候选澄清），确认前结果区不出数；用户选一个口径后再出数。若未澄清直接出数，记下来（触发条件在 PRD 4.2，澄清属内建而非开关），不要为了过题去改算法节点
- T10：rejection（NO_MATCHING_DATA 一类），无表无图，不能编造数字，要有人话原因
- T11：answer，表/图+解读，预热/正式/返场三档期 GMV
- T12：同一会话追问「把刚才那个渠道的GMV按天展开看看」，answer，折线+表，承接上一问的渠道
- T13：answer，饼图+表，新客/老客 GMV 占比
- T14：answer，有表，GMV Top3 类目（验证结果集限幅）
- T15：rejection 或只给退货数据，不给因果结论（归因属边界外）
```

**人审**：是不是真的在浏览器里问的；T10 有没有出假数；T09 澄清前有没有出数；T12 是不是同会话多轮承接；有没有偷偷改字典迁就。

---

## 第 4 轮 · 报表和会话也跑通（仍用本机进程）

```
测例问数已经过了一轮。现在把 F5/F6/F7 在同一套本机进程上点通。不要 Compose，不要登录鉴权（F8 本版可暂缓），不要再改 dw 数据。

在界面上做（接口路径供排查用，正常都走页面）：
1. 用一条已成功的 answer（例如 T01 结果仍在）：点「存为报表」（POST /api/v1/reports，按 turn_id 反查已落库结果），能保存
2. 打开报表列表页（GET /api/v1/reports）：能看到刚存的；点进去（GET /api/v1/reports/{id}）能看到当时的表/图/解读，顶部有快照时间，且没有重新查库
3. 改名（PUT /api/v1/reports/{id}）、删除（DELETE，有确认）：列表随之变
4. 会话页（GET /api/v1/sessions、GET /api/v1/sessions/{id}/messages）：能看到本会话问过的用户句和系统句（含澄清/拒答如果前面有）
5. 澄清中或拒答结果不能存报表（saveable=false，按钮应不可用）

若接口 404/500：先查 app schema 是否初始化、启动 create_all 是否成功（本项目无 alembic），只修接线或初始化，不要改 ChainResult 契约。

交付：上述 5 步各成功/失败 + 失败时的 HTTP 状态和页面现象。小 UI 问题可修；契约问题只记下来。
```

**人审**：打开报表时有没有又打了一次问数；删报表是否真删；有没有为演示去接登录。
