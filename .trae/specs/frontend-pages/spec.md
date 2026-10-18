# 前端页面（frontend-pages）- 需求规格

## Overview
- **Summary**：在仓库根新建 `web/` 纯 SPA（React 18 + Vite 5 + TypeScript 5 + Ant Design 5 + ECharts 5 + Zustand 4 + react-router-dom 6），落地 `docs/SDD-前端.md` v0.2 全部页面与交互：问数页（消息流/过程状态/六类终态）、澄清卡、拒答卡、结果卡片五区、对比呈现、一键存报表、报表列表/查看/刷新/继续问、对话记录；两段式问数（POST 建 turn + EventSource SSE）；并交付 web 容器（node 多阶段构建 → nginx 静态托管 + /api 反代 + SPA 兜底）。
- **Purpose**：P5 三轮 `/spec` 的最后一轮。前端是 ChainResult 的渲染方与唯一用户触点；只消费后端 §3 接口、镜像算法 §6 字段，不另发明接口/链路/业务数字。
- **Target Users**：演示用户（浏览器 http://localhost:8080，单用户本地环境）。

## Goals
- 五个路由（`/chat`、`/chat/:sessionId`、`/reports`、`/reports/:reportId`、`/sessions`）+ 顶栏三入口，默认进问数，跨路由不丢问数状态。
- SSE 两段式问数与 turn 状态机：stage 三行点亮、六终态（answer 非空/空、clarification、rejection 六码、error、cancelled）各有正确组件；取消、断线重连（Last-Event-ID，2 次失败降级）、卸载关流。
- ResultCard 五区严格自上而下；chart mapper 为纯函数（五型 + null），图型本地切换不重查；表/图/解读同源，不做任何业务聚合计算。
- 澄清卡三 input_type、确认前不出数、两轮轮次只渲染服务端 round；recalibrate 入口。
- 报表：保存（saveable 置灰规则 + 同名三选一）、列表（搜索/改名/删除）、查看直读 snapshot、刷新临时替换不覆写、continue-session。
- 对话记录列表与完整还原（同一套消息渲染器）。
- 鉴权两个薄预留（拦截器位、RequireAuth 放行位），无登录 UI。
- 离线可测：vitest + Testing Library + mock fetch/EventSource，后端不存在也能全量验证；`vite build` 通过；web 镜像可构建，nginx 配置三项（静态、SSE 关 buffering、SPA 兜底）齐备。

## Non-Goals
- 不新增/修改任何后端接口、报文字段与链路语义；不计算对比变化值/率（只读 `comparison.changes`）；不缓存/回传口径。
- 不做登录页/账号/权限 UI、仪表盘搭建、报表订阅、跨设备同步、会话全文搜索、收藏置顶。
- 不做 SSR/Next.js、websocket、微前端；不引入 AntD/ECharts/Zustand/RRD 之外的 UI 或状态框架。
- 不起 api/db 容器做联调（后端轮次负责）；本步验收以 mock + 静态构建 + nginx 配置审查为准，浏览器真机联调留到三服务齐后的集成验收（OQ-2）。
- 不修改 `docs/` 任何文件；代码只落在 `web/` 与 compose 的 web 服务增量。

## Background & Context
- 权威：`docs/SDD-前端.md` v0.2；报文以 `docs/SDD-后端.md` §3 为准；字段语义以 `docs/SDD-算法应用.md` §6 ChainResult 为准；产品交互以 `docs/PRD.md` 4.1~4.9 为度。
- 后端轮次尚未实现：所有网络行为经 `api/client.ts` 与 `api/sse.ts` 单点封装，测试以 mock 替身驱动。
- 已发现跨文档常数冲突（已解决）：前端 SDD §3.1 定客户端预校验 500，后端 spec 原暂写 1000——**已统一为 500**，后端 spec FR-2/OQ-5 已跟随修正，三方（前端 SDD/后端 spec/前端 spec）对齐。

## Functional Requirements

### 应用骨架
- **FR-1**：Vite+TS 工程、RouterProvider 五路由（含根 `/` 重定向 `/chat`、未知路由兜底）、AppNav 顶栏三入口；Zustand 三 store（chat/report/session）；`vite build` 严格 TS 通过。
- **FR-2**：`api/types.ts` 手写镜像 ChainResult：Action 联合（answer/clarify/not_answerable/query_gen_failed/query_failed/error 的前端消费形态＝answer/clarification/rejection/error/cancelled 终态）、AnswerEvent（table/chart/insight/caliber/comparison + 信封 turn_id/session_id/question/data_time_range/queried_at/saveable）、ChartSpec 五型枚举与 null、ClarifyPayload（四 reason_code/三 input_type/status）、RejectionPayload（六 reason_code）、ErrorPayload、SSE stage 三值、后端 HTTP 错误信封与错误码联合。
- **FR-3**：`api/client.ts`：fetch 封装（base `/api/v1`、JSON、错误信封解析为类型化错误、请求/响应拦截器位——本版不注入 token、预留 401 分支）；路由层 `<RequireAuth>` 包装位本版直接放行。

### 问数（F1）
- **FR-4**：Composer：空内容置灰；回车发送/Shift+回车换行；客户端长度预校验 500（超长置灰+固定提示，不发请求）；发送后乐观渲染用户气泡。
- **FR-5**：`api/sse.ts` 两段式：POST /chat/turns（question/clarify/recalibrate 三态 + 可选 session_id）→ 202 后建 EventSource；帧按 event 名驱动 turn 状态机 idle→understanding→checking_caliber→querying→终态；终态后等 done 关流；同 stage 去重。
- **FR-6**：断线：重连带 Last-Event-ID；连续 2 次重连失败显示"连接中断，重试"，不重复提交问题；卸载/切换会话关闭旧流；回会话时靠已落库消息还原（不补演过程动画）。
- **FR-7**：ProcessStatus：三阶段固定文案与图标态（✓/转圈/灰），随 stage 点亮；「取消」调 cancel 接口，cancelled 帧后位置替换静态"已取消"，无半成品卡片；cancel 接口本身失败静默（以流终态为准）。
- **FR-8**：终态分发（一个 turn 恰一终态）：answer+rows 非空→ResultCard；answer+rows=[]→EmptyResult（insight 句 + 口径折叠，无图无表无保存）；clarification→ClarifyCard；rejection→RejectMessage；error→ErrorMessage（重试＝原问题重发一轮，原气泡保留）；cancelled→"已取消"。
- **FR-9**：ResultCard 五区：① insight 单行原样；② chart 非 null 才渲染，右上角切换菜单仅列 switchable，切换纯本地；图表 ErrorBoundary 降级"图表暂不可用"且表/解读照常、保存置灰；③ AntD Table 用 label 列名、format 格式化（千分位/百分比）、前端分页 20/50/100、truncated 顶部明示"仅展示前 {display_limit} 行"、tooltip 显值；④ caliber 默认折叠 summary，展开 detail；⑤ 操作区（存为报表/口径不对重新澄清）。
- **FR-10**：多轮追问只带 session_id 发新问；不缓存不回传口径；问完一轮 URL 就地替换为 `/chat/:sessionId`。

### 澄清（F2）
- **FR-11**：ClarifyCard：渲染 title 与 round（1/2，不自计）；single_choice→RadioGroup；time_quick→快捷按钮（本期大促/最近 7 天/自定义，自定义弹 DatePicker 范围）；question_suggestions→2~4 问法按钮，点选直接作为问题发送；「确认并查询」未选择前置灰，确认以 clarify 入参建 turn；「取消」就地收起为"已取消澄清"不发请求；allow_custom_text 时提供"我换个问法"输入（custom selection）。
- **FR-12**：澄清终态消息流不出现任何数字区与保存入口；「口径不对，重新澄清」以 recalibrate{source_turn_id} 建 turn，原结果卡保留为历史。

### 拒答/失败（F3）
- **FR-13**：RejectMessage 统一容器 + 六 reason_code 分支：NOT_DATA_QUESTION/NO_MATCHING_DATA/CALIBER_CONFLICT/GEN_LINT_EXHAUSTED 为业务拒答态（文案全用后端 reason_text，前端不另写；渲染 suggestions 按钮点击即发问）；QUERY_TIMEOUT/QUERY_ERROR 为故障态视觉 + 「重试」（原问题重发），不展示 lint/SQL/码值细节。

### 对比（F4）
- **FR-14**：对比 answer 复用 ResultCard：changes 的 value_delta/rate_delta 作普通字段；rate_delta=null 单元格显示"不可比"（非 0/非无穷大）；grouped_bar/trend_line 由同一 mapper 支持；insight 不追加归因。

### 报表（F5/F6）
- **FR-15**：SaveReportDialog：可点条件＝saveable=true 且图表非降级态；五态置灰 Tooltip 文案按 SDD §3.5 表；Modal 内名称（按问题预填、必填、去空格空名拦截）、只读口径行、chart 缩略（null 则无缩略区）。
- **FR-16**：保存提交 POST /reports：成功关弹窗 + 消息流"已存为报表：《名称》"+ 跳 /reports 链接；409 E_NAME_CONFLICT 切三选一（覆盖重发 overwrite=true/换名留编辑/取消）；其他失败 message.error。
- **FR-17**：/reports 列表：按返回顺序展示名称/创建时间/口径摘要；搜索防抖 300ms 带 q；行内改名（回车/确认 PUT、Esc 取消、空名拦截、409 提示、失败回滚+message.error）；删除二次确认（固定文案"确定删除报表《名称》吗？删除后不可恢复。"）后 DELETE，失败行恢复。
- **FR-18**：/reports/:reportId：只调 GET 详情直渲 snapshot（五区同构、chart=null 无图区），展示 data_time_range/queried_at；无过程态无澄清；「刷新」loading 调 refresh：answer 临时替换 + "本次为刷新结果，尚未保存"标记（快照不变），空结果走 EmptyResult；query_failed 区内超时/失败+重试（再点刷新），query_gen_failed 业务文案+换问法；始终保留口径区与"调整问题继续问"，不用旧数冒新数；打开加载失败保留页头+"加载失败＋重试"不白屏。
- **FR-19**：continue-session：POST 拿 session_id 跳 `/chat/{sessionId}`；失败 message.error。

### 对话记录（F7）
- **FR-20**：/sessions 列表（title=首问、last_question_at、message_count、倒序、分页）；打开跳 /chat/:sessionId，挂载 GET messages 后用**与问数页同一套消息渲染器**按 seq 完整还原（五 type，answer 再分空/非空），还原后可追问；删除二次确认后 DELETE 回列表；界面不设跨设备/搜索/收藏入口。

### 部署（前端侧 F9）
- **FR-21**：`web/Dockerfile` 多阶段（node:20-alpine 构建 → nginx:alpine）；`nginx.conf`：静态托管、`/api/` 反代 api:8000（`proxy_buffering off`、`proxy_read_timeout 300s`）、browser history 的 try_files 兜底；compose 增 web 服务（8080:80，depends_on api）——在后端轮次产出的 `docker-compose.yml`（db/api 两服务）上追加 web 块，本步首次达成三服务 F9（已定：后端 spec OQ-1 本步不含 web 块，归属前端轮次）。
- **FR-22**：/health 首屏弱探测（可选）：degraded 时问数入口给非阻断弱提示；探测失败不阻塞页面。

## Non-Functional Requirements
- **NFR-1（类型安全）**：strict TS；any 仅限测试 mock 边界且集中在 tests；报文联合穷尽性检查（TS never  exhaustiveness）保证六终态/六 reason_code 分支编译期不漏。
- **NFR-2（纯函数可测）**：chart/mapper.ts、utils/format.ts、SSE 状态机 reducer、saveable/置灰判定均为纯函数并配单测；组件测试用 Testing Library，mock 网络不下发真请求。
- **NFR-3（不编数）**：前端代码不做指标聚合、对比计算、阈值判断（如 8%）；所有数字直接取自 payload；grep 可验证无常驻业务常数（档位/枚举值除外）。
- **NFR-4（可构建）**：`npm run build` 零 TS/lint 错误；产物可被 nginx 静态托管；镜像构建不需要 api/db 在线。
- **NFR-5（一致体验）**：所有失败态有可见反馈（不允许点了没反应）；所有文案中文、业务化；不出现技术码/SQL/堆栈/trace。

## Constraints
- **Technical**：React18/Vite5/TS5/AntD5/ECharts5（按需 bar/line/pie）/Zustand4/RRD6/fetch+原生 EventSource；vitest+@testing-library/react（+jsdom）做离线测试；浏览器入口 :8080。
- **Business**：单用户无登录；确认前不出数、拒答不出数、空结果不伪装、解读一句——这些产品铁规则在前端交互上必须有落点。
- **Dependencies**：接口存在以后端轮次为准；本步以契约 fixtures（各终态/各 reason_code/对比/空结果的样例载荷）驱动开发，样例字段与算法 §6 逐字对齐。

## Assumptions
- 源码根 `web/`，测试就近 `web/src/**/*.test.ts(x)` 与 `web/src/test/fixtures/`；样例载荷集中维护，组件与 mapper 共用。
- 开发期 vite dev server 配 `/api` proxy 指向本地 api（可选，纯 mock 测试不依赖）。
- ECharts 按需注册（BarChart/LineChart/PieChart + 必要组件）；trend_line 与 line 共用 line 系列分支。
- 浏览器只针对现代 Chromium/Edge 演示环境，不做兼容矩阵。

## Acceptance Criteria

### AC-1: 类型镜像无遗漏
- **Type**: `rule`
- **When**: 审查 api/types.ts 并编译
- **Then**: Action/五终态/六 reason_code/四 clarify 码/三 input_type/五图型+null/AnswerEvent 五业务字段+信封/Clarify/Rejection/Error/stage 三值与算法 §6、后端 §3 逐字对应；联合分发处启用 exhaustiveness 检查
- **Pass Condition**: tsc 通过且有"故意加一个新联合成员会编译失败"的穷尽性测试/注释守卫；grep 无 narrative/dual_line
- **Evidence**: 类型定义 + build 输出

### AC-2: 五路由与三入口
- **Type**: `rule`
- **When**: 内存路由渲染
- **Then**: `/`→/chat；五路由可达；顶栏三入口；非问数路由切走再回，当前会话消息仍在（store 保活）
- **Evidence**: router 组件测试

### AC-3: Composer 校验
- **Type**: `rule`
- **Given**: 空文本/500 字边界/501 字/Shift 回车
- **When**: 交互
- **Then**: 空与超长置灰不发请求；500 字可发；超长固定提示；Shift+回车换行不发送；回车发送且乐观气泡先出现
- **Evidence**: Composer 测试

### AC-4: SSE 状态机与阶段呈现
- **Type**: `rule`
- **Given**: 脚本化 SSE 帧（三 stage 乱序重复、终态、done）
- **When**: 走一 turn
- **Then**: ProcessStatus 按 understanding→checking_caliber→querying 点亮且同段去重；终态后关闭；状态流转与帧序列严格一致
- **Evidence**: sse reducer 单测 + 组件测试

### AC-5: 取消
- **Type**: `rule`
- **When**: querying 中点取消；cancel 接口失败；随后到 cancelled 帧
- **Then**: 调 cancel；接口失败静默；到帧显示"已取消"且无任何结果卡
- **Evidence**: 组件测试

### AC-6: 断线重连不重复提问
- **Type**: `rule`
- **Given**: 首次流断、连续 2 次重连失败
- **When**: EventSource 重连
- **Then**: 重连带 Last-Event-ID 且不重新 POST 问题；2 次失败显示"连接中断，重试"
- **Evidence**: sse.ts 单测（mock EventSource）

### AC-7: 六终态渲染分发
- **Type**: `rule`
- **Given**: 六类终态 fixtures（含空结果 answer）
- **When**: 消息流渲染
- **Then**: 分别得到 ResultCard/EmptyResult/ClarifyCard/RejectMessage/ErrorMessage/"已取消"；空结果无图无表无保存、显示无数据语义句
- **Evidence**: MessageStream 参数化测试

### AC-8: ResultCard 五区
- **Type**: `rule`
- **When**: 渲染非空 answer
- **Then**: 顺序 insight→chart→table→caliber→操作区；列名取 label；format 千分位/百分比正确；分页 20/50/100 可切；truncated 横幅显示 display_limit；caliber 默认折叠
- **Evidence**: ResultCard 测试

### AC-9: 图型映射与本地切换
- **Type**: `rule`
- **Given**: 五型 chart + null + switchable
- **When**: 调 mapper；菜单切换；模拟渲染异常
- **Then**: 五型各产出正确 option 结构（trend_line 多系列 line、grouped_bar 多系列柱、pie）；null 不调 mapper；切换只改本地 type 无网络请求；渲染异常 ErrorBoundary 降级且保存置灰
- **Pass Condition**: mapper 纯函数单测每型 ≥1 断言（数值直接取自 rows，无数值变换断言外的计算）
- **Evidence**: mapper.test.ts

### AC-10: 澄清卡三型与铁规则
- **Type**: `rule`
- **Given**: 三 input_type fixtures、allow_custom_text
- **When**: 交互
- **Then**: 控件正确；未选确认置灰；确认请求体为 clarify 三态结构；suggestions 点选直接发问；取消就地收起不发请求；custom 展开输入；卡面无数字与保存入口；round 只显示服务端值
- **Evidence**: ClarifyCard 测试

### AC-11: recalibrate
- **Type**: `rule`
- **When**: 点"口径不对，重新澄清"
- **Then**: POST 体含 recalibrate.source_turn_id；原结果卡仍在流中
- **Evidence**: 组件测试

### AC-12: 拒答六码分支
- **Type**: `rule`
- **Given**: 六 reason_code fixtures
- **When**: 渲染 RejectMessage
- **Then**: 四业务码显示 reason_text + suggestions 可点发问（无重试图标）；两 query_failed 码为故障态 + 重试（重发原问题）；文案中无码值/SQL/lint
- **Evidence**: 参数化测试

### AC-13: 对比不可比呈现
- **Type**: `rule`
- **Given**: changes 含 rate_delta=null
- **When**: 渲染表与图
- **Then**: 该格文本"不可比"；无 0/∞；图为 grouped_bar 或 trend_line；insight 原样
- **Evidence**: 组件/mapper 测试

### AC-14: 保存置灰与弹窗
- **Type**: `rule`
- **Given**: SDD §3.5 五态 + 可存态
- **When**: 点保存/输入名称
- **Then**: 五态置灰且 Tooltip 文案各自正确；可存态打开弹窗，预填/空名拦截/缩略区按 chart null 处理
- **Evidence**: 组件测试

### AC-15: 同名冲突三选一
- **Type**: `rule`
- **When**: POST 返回 409 E_NAME_CONFLICT
- **Then**: 弹窗内三分支：覆盖发 overwrite=true、换名留编辑、取消关闭；成功后消息流出现保存成功条与列表链接
- **Evidence**: 组件测试

### AC-16: 报表列表操作
- **Type**: `rule`
- **When**: 搜索/改名/删除的成功与失败路径
- **Then**: 防抖 300ms 带 q；改名 PUT 成功行更新、Esc 撤销、空名拦截、失败回滚+message.error；删除二次确认文案固定、成功移除、失败恢复
- **Evidence**: ReportsPage 测试（假 timers）

### AC-17: 报表查看/刷新/继续问
- **Type**: `rule`
- **Given**: 详情 fixture、刷新四态（answer/空/query_failed/query_gen_failed）、打开失败
- **When**: 进入与操作
- **Then**: 直渲 snapshot 无过程态；时间信息展示；刷新临时替换带未保存标记且不调保存接口；失败各态区内提示且保留口径/继续问入口；详情 GET 失败页头+"加载失败＋重试"；continue-session 跳 /chat/{id}
- **Evidence**: ReportViewPage 测试

### AC-18: 对话记录还原
- **Type**: `rule`
- **When**: 打开历史会话
- **Then**: 按 seq 还原五 type（复用同一渲染器：可通过组件引用同一性检查），空 answer 走 EmptyResult；删除确认后回列表；无搜索/收藏入口
- **Evidence**: SessionsPage/AskPage 测试

### AC-19: 鉴权薄预留
- **Type**: `rule`
- **When**: 审查 client/router
- **Then**: 拦截器存在预留位但不注入 token；401 分支存在但本版不可达；RequireAuth 直接放行；无任何登录/账号组件
- **Evidence**: 代码走读

### AC-20: 构建与 nginx
- **Type**: `rule`
- **When**: npm run build；构建 web 镜像；审 nginx.conf/compose
- **Then**: build 零错误；镜像可产出且不需 api 在线；nginx 含静态、/api 反代 proxy_buffering off + read_timeout 300s、try_files 兜底；compose web=8080:80
- **Evidence**: 构建日志 + 配置文件

### AC-21: 不编数纪律（rubric）
- **Type**: `rubric`
- **Dimension**: 前端对业务数字零加工的纯度
- **Scale**: 1-5
- **Anchors**: 1 = 前端自行算占比/对比率/阈值判定；3 = 展示层有个别格式化外的数值推导；5 = 除 format（千分位/百分号/日期）外无数值计算，全部直出 payload，mapper 仅做结构映射
- **Pass Threshold**: >= 4
- **Evidence**: 代码走读 + grep 业务常数

### AC-22: 交互完成度（rubric）
- **Type**: `rubric`
- **Dimension**: PRD 4.1~4.7 交互细节落地度（置灰、tooltip、二次确认、失败反馈、不白屏）
- **Scale**: 1-5
- **Anchors**: 1 = 主 happy path 外大量无反馈；3 = 关键失败态有提示但细节缺；5 = SDD §3 每个"失败/置灰/确认"点都有可观察落点
- **Pass Threshold**: >= 4
- **Evidence**: 组件测试覆盖清单 + 走读

## Resolved Decisions（已拍板，取代原 Open Questions）
- **OQ-1**：问题长度统一为 **500**（前端 SDD §3.1 为准；后端 spec FR-2/OQ-5 已跟随由 1000 改 500，三方对齐）。
- **OQ-2**：本步 Done = 离线测试 + build + 镜像/nginx 配置审查；浏览器对真实 api 的端到端走查放到三服务齐备后统一验收。
- **OQ-3**：本步在后端产出的 `docker-compose.yml` 上**追加 web 块**（后端已拍板本步不含 web 块，无需合并分支处理）。
- **OQ-4**：/health 首屏弱探测**默认做**（degraded 非阻断提示，探测失败不阻塞）。
