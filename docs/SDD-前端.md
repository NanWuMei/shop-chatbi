# SDD · 前端技术方案

> 版本：v0.2（P4 产出，按算法 SDD v0.4 / 后端 v0.2 对齐重写，待评审）
>
> **相对 v0.1 的关键变化**：
> - 渲染权威改为算法 `ChainResult`（算法 §6）：`api/types.ts` 逐字镜像其 action 联合与 answer/clarify/rejection/error 四套载荷；后端报文是它的信封化切片；
> - 结果字段 `narrative` → **`insight`**；图型枚举改为 `bar | line | trend_line | grouped_bar | pie`（去 `dual_line`）；**`chart` 可为 `null`**（单标量/空结果不画图）；对比载荷新增 `changes[]`（value_delta/rate_delta，`rate_delta=null`＝不可比）；
> - 空结果不再有独立 empty 状态：就是 `answer` 且 `table.rows=[]`、`chart=null`，解读区显示"该范围无数据"语义句；
> - 拒答码空间更新为六个 reason_code；其中 `QUERY_TIMEOUT`/`QUERY_ERROR` 在拒答卡上给「重试」；归因类归 `NOT_DATA_QUESTION`；
> - 「存为报表」可点条件＝`answer` 且 rows 非空（后端 `saveable` 派生字段）。
>
> **接口契约以 [SDD-后端.md](./SDD-后端.md) 第 3 节为报文权威、[SDD-算法应用.md](./SDD-算法应用.md) §6 为字段语义权威**。本文件只写页面、交互怎么落地，以及前端如何调用这些接口。若文档冲突：**先改 [SDD-总览.md](./SDD-总览.md) 的衔接/对照，再同步修改本文件与后端文档**，不得各自妥协。

---

## 1. 技术决策（写死一版）

| 决策点 | 结论 | 理由 |
|---|---|---|
| 框架 | **React 18 + Vite 5 + TypeScript 5**（纯 SPA） | 本版无 SSR/SEO 需求；SPA 构建为静态产物交给 nginx，正好匹配 Compose 三服务拓扑 |
| UI 组件库 | **Ant Design 5** | 对话流、弹窗、二次确认、表格分页、消息提示开箱即用；中文生态友好，演示阶段不投入样式工程 |
| 图表 | **ECharts 5**（按需引入 bar/line/pie 系列） | bar/line/pie/分组柱/对比趋势线全部原生支持（trend_line 走多系列 line 分支）；悬浮显值为默认能力 |
| 状态管理 | **Zustand 4** | 对话/报表状态轻量，避免 Redux 样板；跨路由不丢对话状态主要靠它 + 服务端持久化双保险 |
| 路由 | react-router-dom 6 | 问数/报表/对话记录三入口 |
| 网络 | fetch 封装 + **浏览器原生 EventSource（SSE）** | 过程状态必须流式；问数建连用 POST，事件流用 GET，无需 websocket |
| 不选 Next.js | — | 引入 SSR/node 运行时只会让部署变重，对 PRD 无收益 |

---

## 2. 页面与信息架构

单页三入口顶栏：「问数」「报表」「对话记录」；首次打开默认进「问数」；切换入口不丢当前问数状态（Zustand 保活 + 会话已在服务端落库）。

| 路由 | 页面 | 进出方式 |
|---|---|---|
| `/chat` | 问数页（新会话） | 默认首页；问完一轮后 URL 就地替换为 `/chat/:sessionId` |
| `/chat/:sessionId` | 问数页（指定会话） | 从对话记录打开、"基于报表继续问"跳入；可继续追问 |
| `/reports` | 报表列表 | 顶栏进入；搜索框、改名/删除在本页完成 |
| `/reports/:reportId` | 报表查看页 | 点列表卡片进入；左上「返回列表」 |
| `/sessions` | 对话记录列表 | 顶栏进入；点条目进 `/chat/:sessionId` |

**问数页布局（严格按 PRD 4.1）**：上部消息流，底部输入框＋发送按钮。消息流中顺序出现：用户气泡 → 过程状态 → 终态消息（澄清卡 / 拒答卡 / 空结果 / 错误 / 结果卡片）。

**结果卡片内部自上而下（五区固定）**：① 一句解读 → ② 图表（`chart=null` 时本区整体不渲染）→ ③ 数据表 → ④ 口径摘要（默认折叠一行）→ ⑤ 操作区（存为报表 / 口径不对重新澄清）。

---

## 3. 各功能的前端交互实现

### 3.1 F1 对话问数

**提问与输入**

- Composer：空内容发送按钮置灰；回车发送、Shift+回车换行；
- 客户端长度预校验 500 字（与后端一致）：超长时按钮置灰并提示"问题过长，请缩短或拆分"，不发请求；
- 发送即乐观渲染用户气泡，随后进入过程状态。

**过程状态（ProcessStatus 组件）**

- 三阶段固定顺序：正在理解问题 → 正在核对口径 → 正在取数；随 SSE `stage` 事件点亮（已完成✓ / 进行中转圈 / 未开始灰），同阶段事件去重；
  - 与算法 8 步的映射由后端完成，前端只认三个 stage 值：`understanding`（S1）/ `checking_caliber`（S2/S3/S4）/ `querying`（S5/S6/S7/S8）；
- 期间显示「取消」按钮：点击调 `POST /chat/turns/{id}/cancel`，流上到达 `cancelled` 帧后，该位置替换为静态文本"已取消"（不渲染任何半成品卡片）。

**终态消息渲染（按 ChainResult.action / SSE 终态事件分发，一个 turn 恰好一个终态）**

| 终态 | 组件 | 渲染要点 |
|---|---|---|
| `answer` 且 `table.rows` 非空 | ResultCard | 五区，见下 |
| `answer` 且 `table.rows=[]` | EmptyResult | 空结果同构 answer：显示 `insight`（"该范围无数据"语义句）＋口径折叠区；**不画图、不画空表、无保存入口**；不用 0/空表伪装 |
| `clarification` | ClarifyCard | 见 3.2 |
| `rejection` | RejectMessage | 见 3.3；按 reason_code 分文案与按钮 |
| `error` | ErrorMessage | 业务化错误文案 + 「重试」；重试 = 用原问题重新发起一轮（原失败气泡保留）；不展示错误码/SQL/堆栈 |
| `cancelled` | 文本"已取消" | 无操作按钮 |

**ResultCard 五区实现**

1. **一句解读**：单行渲染 `insight`（后端/算法 Writer 产出，前端不改写、不追加内容）；
2. **图表**：`chart=null` 时本区不渲染；非 null 时 ECharts 渲染，右上角图型切换菜单只列出 `chart.switchable` 中的类型，切换为**纯前端本地行为**（不重新请求）；图表渲染失败用 ErrorBoundary 降级为"图表暂不可用"，**数据表与解读照常展示**，此时「存为报表」置灰（PRD 4.1）；
3. **数据表**：AntD Table 渲染 `table.columns/rows`，列名用 `label`（业务名），数字按 `format` 格式化（金额千分位、% 等）；前端分页（页大小可选 20/50/100）；`truncated=true` 时表格顶部明示"仅展示前 {display_limit} 行"；图表悬浮显值由 ECharts tooltip 默认承担；
4. **口径摘要**：默认折叠只显示 `caliber.summary` 一行；点"查看口径"展开 `caliber.detail`（指标/维度/时间范围/筛选/对比）；
5. **操作区**：「存为报表」（3.5）、「口径不对，重新澄清」（3.2 末）。

**多轮追问**：输入框始终可用；前端只负责带 `session_id` 发新问题，上文口径承接完全由算法 S1（后端传入最近口径摘要）完成，前端不缓存、不回传口径。

### 3.2 F2 澄清（ClarifyCard）

- 标题渲染 `title`（如"请确认类目口径"），轮次仅按 `round` 展示（1/2），不自行计数；
- 按 `input_type` 出控件：
  - `single_choice`：AntD RadioGroup 渲染 `options`（按钮式单选）；
  - `time_quick`：快捷按钮（本期大促/最近 7 天/自定义），自定义弹日期范围选择器；
  - `question_suggestions`：渲染 `suggestions` 中的 2~4 个具体问法按钮，**点选即直接作为问题发送**（不等同于选项确认）；
- 底部「确认并查询」：未选择前置灰；点击后以 `clarify:{clarify_id, selection}` 调 `POST /chat/turns`，随后进入新一轮过程状态；
- 「取消」：卡片就地收起为"已取消澄清"，不发请求、不出数；
- 「我换个问法」（`allow_custom_text=true` 时出现）：展开输入框，提交时按 `selection.type=custom` 发送（后端拼成 clarified_question，从 S1 重入）；
- **前端铁规则：clarification 终态下消息流里绝不出现任何数字区域，「存为报表」不存在于该消息上**；
- 「口径不对，重新澄清」（结果卡片区⑤）：调 `POST /chat/turns` 携带 `recalibrate:{source_turn_id}`；后端带原 QuerySpec 令算法从 S4 强制重新出澄清卡；原结果卡片保留为历史不动。

### 3.3 F3 拒答与失败（RejectMessage）

统一渲染 `rejection` 终态（算法三类 action 六种 reason_code 同构）：明确展示"不能回答/本次没跑出来" + `reason_text`（大白话），不出表、不出图、不出解读、无保存入口。按 reason_code 分支：

| reason_code | 归属 action | 前端呈现 |
|---|---|---|
| `NOT_DATA_QUESTION` | not_answerable | 闲聊/归因/预测类；文案固定"我不算原因，但可以给你相关数据"语气（文案用后端 `reason_text`，前端不另写）；渲染 `suggestions` 问法按钮，点了才正常问数 |
| `NO_MATCHING_DATA` | not_answerable | 库中无对应数据/超数据覆盖；渲染 `suggestions`（如同比不行建议环比、可答指标按钮） |
| `CALIBER_CONFLICT` | not_answerable | 口径矛盾说明 + `suggestions` 换问法 |
| `GEN_LINT_EXHAUSTED` | query_gen_failed | 生成多次未过技术校验；给「换个问法」引导（suggestions），**不展示 lint 细节** |
| `QUERY_TIMEOUT` | query_failed | "取数超时"样式（区别于业务拒答，带重试图标）＋「重试」按钮：用原问题重发一轮 |
| `QUERY_ERROR` | query_failed | "取数失败"＋「重试」按钮，规则同上；不出半截数 |

- `suggestions` 按钮统一行为：点击即把 `question` 作为新问题发送；
- 样式上两类 `query_failed` 用故障态视觉（可重试），其余四类用业务拒答态视觉（无重试图标）。

### 3.4 F4 对比

无独立页面：对比类 `answer` 复用 ResultCard，差异完全由载荷驱动（算法 §4 ComparisonSpec）：

- 数据表：后端已给各时段并列列；`comparison.changes[]` 中的变化值 `value_delta`、变化率 `rate_delta` 按普通字段渲染；`rate_delta=null` 的"不可比"单元格原样显示文本"不可比"，不渲染成 0 或无穷大；
- 图表：`type=grouped_bar`（分组柱）或 `trend_line`（多系列对比折线）由同一个 chart→option 映射器支持；
- 解读：单行 `insight`，只陈述方向与幅度（"GMV 同比增长 18.3%"），前端不特殊处理、不追加归因。

### 3.5 F5 一键成报表（SaveReportDialog）

**置灰规则（前端第一关，与后端 `E_REPORT_NOT_SAVEABLE` 第二关对应）**：仅 `saveable=true`（= `answer` 且 rows 非空）且图表未处于渲染失败降级态时可点；其余状态置灰，悬浮 Tooltip 给原因：

| 状态 | 提示 |
|---|---|
| 澄清进行中/已取消澄清 | 请先完成口径确认 |
| rejection（业务拒答/生成失败） | 该结果无法保存 |
| answer 空结果（rows=[]） | 暂无数据，无法保存 |
| QUERY_TIMEOUT/QUERY_ERROR/error/已取消 | 取数未成功，无法保存 |
| 图表渲染失败 | 图表加载失败，暂不能保存 |

**弹窗**：AntD Modal——名称输入框（按问题预填、可改、必填、去空格后空名拦截）；只读展示口径摘要一行与图表缩略图（用 `chart` 小尺寸渲染；`chart=null` 时不显示缩略区）；「确认保存」「取消」。

**提交与同名处理**：

1. `POST /reports {turn_id, title}`；成功：关弹窗，消息流出现"已存为报表：《名称》"＋「去报表列表查看」链接（跳 `/reports`）；
2. `409 E_NAME_CONFLICT`：弹窗内切换为三选一——「覆盖」（重发 `overwrite=true`）/「换个名字」（留在弹窗编辑）/「取消」；
3. 取消：不保存，结果卡片保留。

### 3.6 F6 报表列表与查看

**列表页 `/reports`**

- AntD List/Table，按返回顺序（保存时间倒序）展示：名称、创建时间、口径一句话摘要；
- 顶部名称搜索框（防抖 300ms，调 `?q=`；本版只做名称包含匹配）；
- 每条操作：点卡片/名称打开；「改名」→ 行内变输入框，回车/确认调 PUT，Esc 取消，空名前端拦截；「删除」→ 二次确认 Modal（"确定删除报表《名称》吗？删除后不可恢复。"）→ DELETE；
- 改名/删除失败（网络/5xx）：列表保持原状 + message.error("操作失败，请重试")，不允许"点了没反应"。

**查看页 `/reports/:reportId`**

- 进入只调 `GET /reports/{id}`，**直接渲染 snapshot**（`{insight, chart, table, comparison}`）：布局与结果卡片一致（解读/图/表/口径，`chart=null` 无图区），并显示"数据时间 {data_time_range}，取数时间 {queried_at}"；页面上不出现任何过程状态、不出现澄清；
- 「刷新」：调 `POST /reports/{id}/refresh`，按钮 loading；接口同步返回终态同构体——
  - `action=answer`：用其载荷**临时替换**当前展示，并打标"本次为刷新结果，尚未保存"（快照不变）；rows 为空按 EmptyResult 渲染；
  - `action=query_failed`（QUERY_TIMEOUT/QUERY_ERROR）：区内显示"取数失败/超时＋重试"（重试即再点一次刷新）；`query_gen_failed`：显示业务化失败文案与换问法引导；
  - 任何情况保留口径区与「调整问题继续问」入口，不用旧数字冒充新数字；
- 「基于这个问题继续问」：调 `POST /reports/{id}/continue-session` 拿 `session_id` 后跳 `/chat/{sessionId}`；
- 打开时加载失败：保留页头与报表名，数据区显示"加载失败＋重试"，不白屏。

### 3.7 F7 对话记录（/sessions）

- 列表项：首问作标题、最近提问时间、问答条数（`message_count`）；倒序；
- 打开：跳 `/chat/:sessionId`，挂载时调 `GET /sessions/{id}/messages`，按 `seq` 用与问数页**同一套消息渲染器**完整还原（user/clarification/answer/rejection/note 全覆盖；answer 再按 rows 是否为空分 ResultCard/EmptyResult）；还原后可直接在输入框追问；
- 删除：二次确认（文案同报表删除）→ DELETE → 回列表；
- 本版不做跨设备同步、全文搜索、收藏置顶（PRD Out），界面不设这些入口。

### 3.8 F9 可部署（前端侧）

- `vite build` 产出静态文件，由 web 容器 nginx 托管；API 基路径固定 `/api/v1`（同源反代，无 CORS 配置负担）；
- nginx 对 `/api/` 配 `proxy_buffering off` 保证 SSE 实时；
- 前端路由用 browser history，nginx 配 `try_files ... /index.html` 兜底。

---

## 4. 前端调用的后端接口清单

> 报文字段以后端文档 §3 + 算法 §6 为准，本表只列触发时机、关键入参、前端处理。

| 接口 | 方法 | 触发时机 | 关键入参 | 成功处理 | 失败展示 |
|---|---|---|---|---|---|
| `/chat/turns` | POST | 发送问题/确认澄清/换问法/重新澄清 | `question` 或 `clarify{clarify_id,selection}` 或 `recalibrate{source_turn_id}`；`session_id` | 得 turn_id 后立刻建 EventSource | 400 内联提示；409 澄清失效则提示重问 |
| `/chat/turns/{id}/events` | GET(SSE) | 建 turn 成功后立即 | — | 按 stage/终态事件（answer/clarification/rejection/error/cancelled）渲染 | 流错误（非终态）：连接中断按 Last-Event-ID 自动重连一次，再失败显示"连接中断，重试" |
| `/chat/turns/{id}/cancel` | POST | 点「取消」 | — | 等 cancelled 帧 | 静默：终态以事件流为准 |
| `/sessions` | GET | 进对话记录页 | `offset/limit` | 渲染列表 | 列表区错误态 + 重试 |
| `/sessions/{id}/messages` | GET | 打开会话 | — | 还原消息流 | 错误态 + 返回列表 |
| `/sessions/{id}` | DELETE | 确认删除会话 | — | 移除条目 | message.error，列表不变 |
| `/reports` | POST | 保存弹窗确认 | `turn_id,title,overwrite?` | 成功提示+列表链接 | 409 弹同名三选一；其余 message.error |
| `/reports?q=` | GET | 进报表页/搜索 | `q,offset,limit` | 渲染列表 | 错误态+重试 |
| `/reports/{id}` | GET | 打开报表 | — | 直接渲染 snapshot | "加载失败＋重试"占位 |
| `/reports/{id}` | PUT | 改名确认 | `title` | 行内更新 | 409 提示改名冲突；其余失败回滚 |
| `/reports/{id}` | DELETE | 确认删除报表 | — | 移出列表 | message.error，行恢复 |
| `/reports/{id}/refresh` | POST | 报表页点刷新 | — | answer 临时替换+未保存标记；空结果 EmptyResult | query_failed/query_gen_failed 区内失败态，不伪造 |
| `/reports/{id}/continue-session` | POST | 点"继续问" | — | 跳 `/chat/{sessionId}` | message.error |
| `/health` | GET | （可选）首屏探测 | — | degraded 时问数入口给弱提示 | 不阻塞页面 |

错误分支依据两层码值：

1. **HTTP 错误信封**（后端 §8）：可重试类（`E_LLM_UNAVAILABLE`/`E_INTERNAL`）给「重试」；校验/冲突类给具体操作引导；
2. **rejection 载荷 reason_code**（算法 §6）：`QUERY_TIMEOUT`/`QUERY_ERROR` 给重试，其余给问法引导；
3. **任何错误都不向用户展示 SQL、堆栈、trace 与原始技术码**。

---

## 5. SSE 客户端机制（`api/sse.ts`）

1. 问数是"两段式"：`POST /chat/turns` 拿 `turn_id`（202）→ `new EventSource('/api/v1/chat/turns/{id}/events')`；
2. 每帧按 `event` 名分派到 Zustand 中当前 turn 的状态机：`idle → understanding → checking_caliber → querying → 终态`；
3. 收到任一终态事件（answer/clarification/rejection/error/cancelled）后等待 `done` 帧关闭连接；
4. 断线重连：EventSource 自动重连时带 `Last-Event-ID`（服务端 10 分钟缓冲）；连续 2 次重连失败降级为"连接中断，重试"，不重复提交问题；
5. 页面卸载/切换会话：旧 EventSource 关闭，旧 turn 若仍 running，回该会话时靠已落库消息还原（过程动画不补演）。

---

## 6. 图表怎么出（职责切分）

- **算法负责"画什么"**：S7 Presenter 给声明式 `chart{type,x_field,series,switchable}`（五型：`bar`/`line`/`trend_line`/`grouped_bar`/`pie`），不关心渲染库；单标量与空结果给 `chart=null`；
- **前端负责"怎么画"**：`chart/mapper.ts` 是一个**纯函数**，把 chart + rows 映射成 ECharts option——柱状/折线/趋势多系列/分组柱/饼各一个分支（`line` 与 `trend_line` 共用 line 系列实现，区别在系列数量与对比语义），数字格式化复用 `utils/format.ts`；
- 这样保证表、图、解读同源：三者都来自同一个 `answer` 载荷（table.rows / chart / insight），前端不做任何聚合计算（对比的变化值/率由算法代码 Decimal 算好放在 `comparison.changes[]`）；
- 图型切换只换 mapper 的 type 分支再渲染，不重查；不在 switchable 内的类型菜单不出；`chart=null` 不调用 mapper；
- mapper 必须是纯函数且有单测（P5 harness 规格覆盖），避免图表层"二次算错数"。

---

## 7. 鉴权本版怎么处理

- **本版无登录页、无 token、无 401 跳转**：应用打开即用，报表/对话均为单用户空间（PRD 4.8 暂缓项）；
- 前端仍做两个**预留动作**，使以后加登录不重构：
  1. `api/client.ts` 统一留请求拦截器位置（本版不注入任何 token）；响应拦截器预留 401 分支（本版后端不会返回）；
  2. 路由层预留 `<RequireAuth>` 包装位（本版实现为直接放行），不写任何假账号 UI；
- 不假装"永远不需要登录"：产品定位与暂缓说明以 PRD 4.8 为准，角色/行列级权限不做前端预演。

---

## 8. 前端目录草案（与总览目录树一致）

```text
web/
├─ Dockerfile                # 多阶段：node:20-alpine 构建 → nginx:alpine
├─ nginx.conf                # 静态托管 + /api 反代（SSE 关 buffering）+ SPA 兜底
├─ package.json / vite.config.ts / tsconfig.json
└─ src/
   ├─ main.tsx / App.tsx / router.tsx
   ├─ api/
   │  ├─ client.ts           # fetch 封装、拦截器预留、错误信封解析
   │  ├─ sse.ts              # 两段式问数、重连、turn 状态机
   │  └─ types.ts            # ChainResult 的 TS 镜像（单一来源手写对齐）：
   │                         #   Action 联合 + answer 载荷{table,chart,insight,caliber,comparison}
   │                         #   + ClarifyPayload + RejectionPayload（六 reason_code）+ ErrorPayload
   ├─ store/
   │  ├─ chatStore.ts        # 当前会话、消息流、turn 阶段
   │  ├─ reportStore.ts      # 列表/详情/刷新临时态
   │  └─ sessionStore.ts
   ├─ pages/
   │  ├─ AskPage.tsx / ReportsPage.tsx / ReportViewPage.tsx / SessionsPage.tsx
   ├─ components/
   │  ├─ layout/AppNav.tsx
   │  ├─ chat/
   │  │  ├─ MessageStream.tsx / UserBubble.tsx / ProcessStatus.tsx
   │  │  ├─ ClarifyCard.tsx / RejectMessage.tsx / EmptyResult.tsx / ErrorMessage.tsx
   │  │  ├─ Composer.tsx
   │  │  └─ ResultCard/{index.ts,Insight,ChartView,DataTable,Caliber,Actions}.tsx
   │  └─ reports/
   │     ├─ SaveReportDialog.tsx / ReportList.tsx / NameConflictStep.tsx
   ├─ chart/
   │  ├─ mapper.ts           # chart + rows -> ECharts option 纯函数（五型分支；null 不调用）
   │  └─ echarts.ts          # 按需注册 bar/line/pie
   └─ utils/format.ts         # 金额/百分比/日期，表与图共用
```

---

## 9. 关联文档

- 接口/SSE/HTTP 错误码权威：[SDD-后端.md](./SDD-后端.md)
- 链路状态、终态语义与 ChainResult 字段权威：[SDD-算法应用.md](./SDD-算法应用.md)
- 全局架构、PRD F1~F9 对照、衔接时序：[SDD-总览.md](./SDD-总览.md)
