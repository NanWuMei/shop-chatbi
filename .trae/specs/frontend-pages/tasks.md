# 前端页面（frontend-pages）- 实现计划

> 离线优先：全部任务可用 `npm run test`（vitest + jsdom）与 `npm run build` 验收，不依赖 api/db。
> 网络层单点：所有 HTTP/SSE 行为只经 `src/api/client.ts`、`src/api/sse.ts`；测试通过契约 fixtures（`src/test/fixtures/`，字段逐字对齐算法 §6/后端 §3）与 mock fetch/EventSource 驱动。
> OQ-1~OQ-4 已拍板（见 spec.md Resolved Decisions）：问题长度统一 500；compose 在后端产出的 docker-compose.yml 上追加 web 块；/health 弱探测默认做；真机端到端留三服务齐备后统一验收。

## Task 1: 工程脚手架与依赖
- **Status**: `done`
- **Priority**: high
- **Depends On**: None
- **Description**: `web/` 初始化 Vite5+React18+TS5（strict）；装 antd5、echarts5、zustand4、react-router-dom6；vitest、@testing-library/react、@testing-library/user-event、jsdom、fake timers 配置；npm scripts（dev/build/test）；vite.config 严格构建 + 可选 /api dev proxy 注释样例；目录按 SDD §8 建空骨架。
- **Acceptance Criteria Addressed**: AC-20
- **Test Requirements**:
  - `rule` TR-1.1: `npm run build` 零错误（空壳页面）；`npm run test` 通过；证据：命令输出。
  - `rule` TR-1.2: tsc 对 any 泄漏开启 strict/noUnusedLocals；证据：tsconfig + build 输出。

## Task 2: 类型镜像与契约 fixtures
- **Status**: `done`
- **Priority**: high
- **Depends On**: Task 1
- **Description**: `api/types.ts` 逐字镜像 ChainResult 与后端信封（见 FR-2）；穷尽性分发工具（never 守卫）；`src/test/fixtures/` 产契约样例：非空 answer（bar）、空结果 answer、line/trend_line/grouped_bar/pie 各一、对比 answer（含 rate_delta=null、truncated=true）、四码 clarification × 三 input_type、六 reason_code rejection、error、cancelled、SSE 帧序列、409/400/502 错误信封、reports 列表/详情/刷新四态、sessions 列表/消息。
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-2.1: 一个 exhaustive switch 测试：临时给联合加成员必须编译失败（以代码注释/守卫测试留证）；证据：tsc。
  - `rule` TR-2.2: grep 全仓无 narrative、dual_line、reason_code 拼写外的旧术语；证据：检查输出。
  - `rule` TR-2.3: fixtures 通过 TS 类型校验（即与 types 一致）；证据：测试编译。

## Task 3: API client、SSE 引擎与错误模型
- **Status**: `done`
- **Priority**: high
- **Depends On**: Task 2
- **Description**: `api/client.ts`：base /api/v1、JSON 封装、错误信封→类型化 ApiError（保留 code 供分支、用户侧只出业务文案）、拦截器预留位与 401 空分支；封装 13 个接口调用函数（SDD §4 表）。`api/sse.ts`：两段式建流、turn 状态机纯 reducer（idle→三 stage→终态→done）、同段去重、Last-Event-ID 重连计数（2 次失败降级）、卸载关流、不重复 POST；可注入 EventSource 工厂以便测试。
- **Acceptance Criteria Addressed**: AC-4, AC-6, AC-19
- **Test Requirements**:
  - `rule` TR-3.1: mock fetch 覆盖 13 接口的 URL/方法/请求体/错误信封分支；证据：单测。
  - `rule` TR-3.2: mock EventSource 脚本化帧：状态机序列、去重、done 关闭、重连带 Last-Event-ID、2 次失败降级、断流期间无重复 POST；证据：sse 单测。
  - `rule` TR-3.3: 代码走读：无 token 注入、无登录跳转；证据：走读。

## Task 4: 路由、布局、store
- **Status**: `done`
- **Completion Evidence**: router.tsx（五路由+/重定向+兜底+RequireAuth 放行位）+ routes 导出供测试；AppNav/RequireAuth/Layout；chatStore（ask/confirmClarify/recalibrate/cancel/loadSession/草稿保活/互斥锁）、reportStore、sessionStore。`router.test.tsx` TR-4.1/TR-4.2 通过。
- **Priority**: high
- **Depends On**: Task 3
- **Description**: router.tsx 五路由 + `/` 重定向 + 404 兜底 + RequireAuth（放行包装位）；AppNav 顶栏三入口；三 Zustand store：chatStore（当前 sessionId/messages/当前 turn 状态机/发起问题/确认/取消动作）、reportStore（列表/详情/刷新临时态）、sessionStore（列表）；跨路由保活。
- **Acceptance Criteria Addressed**: AC-2
- **Test Requirements**:
  - `rule` TR-4.1: 内存路由渲染全部路径与重定向；证据：组件测试。
  - `rule` TR-4.2: 切到 /reports 再回 /chat，消息流与输入内容不丢；证据：组件测试。

## Task 5: 问数页：Composer/ProcessStatus/消息流/取消
- **Status**: `done`
- **Completion Evidence**: AskPage + Composer（空/500/回车发送/Shift+回车/超长固定提示）+ ProcessStatus（三行三态图标+取消）+ MessageStream（同一渲染器+自动滚底）+ UserBubble；URL 就地替换由 onSessionReady 完成。`Composer.test.tsx`（TR-5.1）、`MessageEntry.test.tsx`（阶段点亮/取消/cancelled 替换/连接中断）、`chatStore.test.ts`（乐观气泡/互斥/done 解锁/onLost）通过。
- **Priority**: high
- **Depends On**: Task 4
- **Description**: AskPage 布局（上流下输入）；Composer（空置灰、500 字预校验、回车/Shift+回车、乐观气泡）；ProcessStatus（三阶段三态、取消按钮、cancelled→"已取消"）；MessageStream + UserBubble；挂载 /chat/:id 时 GET messages 还原（与 Task 9 共用渲染器）；首轮后 URL 替换 sessionId；卸载关流。
- **Acceptance Criteria Addressed**: AC-3, AC-5
- **Test Requirements**:
  - `rule` TR-5.1: 500 边界、空、Shift+回车、乐观气泡断言；证据：测试。
  - `rule` TR-5.2: 脚本化帧下阶段点亮顺序/去重；取消静默路径与 cancelled 替换；证据：测试。

## Task 6: 六终态组件 + 澄清卡 + 拒答卡
- **Status**: `done`
- **Completion Evidence**: MessageEntry 穷尽 switch 分发器（assertNever 守卫）+ EmptyResult/ErrorMessage/ClarifyCard（三 input_type+custom+suggestions 直问+取消不发请求+round 直显）/RejectMessage（六码两视觉态+故障码重试）。`MessageEntry.test.tsx` 六终态参数化断言、`ClarifyCard.test.tsx` 三控件交互与请求形状、卡面无表格/保存。
- **Priority**: high
- **Depends On**: Task 5
- **Description**: 终态分发器（穷尽 switch）；EmptyResult；ErrorMessage（重试重发原问、旧气泡保留）；ClarifyCard（三 input_type、custom、suggestions 直问、确认 clarify、取消收起、round 直显、无数字区）；RejectMessage（六码两视觉态、suggestions 发问、两故障码重试）；recalibrate 操作在结果卡先占位（Task 7 接动作）。
- **Acceptance Criteria Addressed**: AC-7, AC-10, AC-11, AC-12
- **Test Requirements**:
  - `rule` TR-6.1: fixtures 参数化六终态渲染断言；证据：测试。
  - `rule` TR-6.2: 澄清各控件交互与请求体形状；未选置灰；卡面 grep 无表格/保存；证据：测试。
  - `rule` TR-6.3: 六 reason_code 文案/按钮/视觉类名分支断言；用户可见文本无技术码；证据：测试。

## Task 7: ResultCard 五区 + chart mapper + format
- **Status**: `done`
- **Completion Evidence**: utils/format.ts（money/number:number:2/percent/percent:2/日期/范围/questionSendable）+ chart/echarts.ts 按需注册 + chart/mapper.ts 纯函数五型 + ResultCard 五区（Insight/ChartView 切换菜单仅 switchable 且本地切换+ErrorBoundary+try/catch 双降级/DataTable 分页 20/50/100+truncated 横幅+不可比/Caliber 折叠/Actions 置灰+recalibrate）。`mapper.test.ts`（TR-7.1 五型数值直出）、`format.test.ts`、`saveable.test.ts` 表驱动、`MessageEntry.test.tsx`（不可比/切换）。
- **Priority**: high
- **Depends On**: Task 6
- **Description**: utils/format.ts（金额千分位、% 直显/格式、日期）；chart/echarts.ts 按需注册；chart/mapper.ts 纯函数五型分支（null 不调用、trend_line 多系列 line、grouped_bar、pie）；ResultCard 子组件：Insight（原样单行）、ChartView（切换菜单仅 switchable、本地切换、ECharts、ErrorBoundary 降级）、DataTable（label 列、format、20/50/100 分页、truncated 横幅）、Caliber（折叠）、Actions（保存置灰规则接 Task 8、recalibrate 发 source_turn_id）。
- **Acceptance Criteria Addressed**: AC-8, AC-9, AC-13, AC-21
- **Test Requirements**:
  - `rule` TR-7.1: mapper 五型 × 数值直出断言（数值与 rows 一一对应、无派生数）；null 返回不调用；证据：mapper.test.ts。
  - `rule` TR-7.2: 切换菜单点击无网络请求（mock 计数）；渲染抛错时降级文案出现且保存置灰；证据：组件测试。
  - `rule` TR-7.3: 分页档位、truncated 横幅、format 格式、折叠默认态；rate_delta=null 显"不可比"；证据：组件测试。
  - `rubric` TR-7.4: AC-21 不编数 ≥4；证据：走读 + grep。

## Task 8: 报表保存/列表/查看/刷新/继续问
- **Status**: `done`
- **Completion Evidence**: SaveReportDialog（预填/口径只读行/chart 缩略 null 不渲染/409→NameConflictStep 覆盖=overwrite 重发/换名/取消）+ NameConflictStep + ReportsPage（300ms 防抖搜索/行点击/重命名 Modal/删除二次确认）+ ReportViewPage（直渲 snapshot/刷新四态临时替换/继续问跳转）。`SaveReportDialog/index.test.tsx`（409 三分支请求体+空名置灰）、`reportStore.test.ts`（刷新四态+快照不变+rename/remove）。改名 409 分支由 client 层 ApiError.existing 承载（列表页走 store 错误 toast，见走读注记）。
- **Priority**: high
- **Depends On**: Task 7
- **Description**: SaveReportDialog（五态置灰 Tooltip、预填/空名、缩略图按 chart null、409 三选一步 NameConflictStep、成功消息条+列表链接）；ReportsPage + ReportList（顺序展示、300ms 防抖 q、行内改名 PUT/Esc/409/失败回滚、删除二次确认固定文案/恢复）；ReportViewPage（GET 直渲 snapshot、时间信息、刷新按钮 loading 与四态临时替换+未保存标记、失败保留口径区、加载失败不白屏、continue-session 跳转、/health 弱提示按 OQ-4）。
- **Acceptance Criteria Addressed**: AC-14, AC-15, AC-16, AC-17
- **Test Requirements**:
  - `rule` TR-8.1: 五态 Tooltip 文案与置灰逐态断言；证据：测试。
  - `rule` TR-8.2: 409 三分支请求体与弹窗状态；成功条与链接；证据：测试。
  - `rule` TR-8.3: 防抖假 timers、改名三路径、删除确认/恢复；证据：测试。
  - `rule` TR-8.4: 详情直渲（无 SSE/turns 调用断言）、刷新四态且不调保存接口、空结果 EmptyResult、GET 失败页头保留、跳转 sessionId；证据：测试。

## Task 9: 对话记录页与会话还原
- **Status**: `done`
- **Completion Evidence**: SessionsPage（标题/消息数/最后提问/创建时间/打开/删除二次确认）；AskPage 挂载 /chat/:id 时 loadSession → messageToEntry 五 type 映射 → 同一 MessageEntry 渲染器还原（TR-9.2：AskPage 与 SessionsPage 均仅引用 components/chat/MessageEntry 链路）。`chatStore.test.ts` loadSession 用例（含空结果/note/澄清终态）。
- **Priority**: medium
- **Depends On**: Task 6
- **Description**: SessionsPage（首问标题/最近时间/message_count、倒序、分页）；条目跳 /chat/:id；AskPage 挂载分支：已有 sessionId 时 GET messages 用**同一渲染器**按 seq 还原五 type（复用 Task 6 分发器，不得另写一套）；删除二次确认后回列表；页面不设搜索/收藏/跨设备入口。
- **Acceptance Criteria Addressed**: AC-18
- **Test Requirements**:
  - `rule` TR-9.1: 列表字段/顺序/分页；还原消息类型与顺序（含空结果、note、澄清终态 status）；删除路径；证据：测试。
  - `rule` TR-9.2: 静态检查 AskPage 与 SessionsPage 引用同一消息渲染模块；证据：import 扫描。

## Task 10: Dockerfile、nginx.conf、compose web 与最终构建验收
- **Status**: `done`
- **Completion Evidence**: web/Dockerfile（node:22-alpine 构建→nginx:1.27-alpine）+ web/nginx.conf（try_files 兜底 + /api/v1 反代 api:8000 + proxy_buffering off + read_timeout 300s）+ .dockerignore + compose 追加 web（127.0.0.1:8080:80，api 改 expose 内网）。镜像构建本机无 Docker 留人工（见 checklist F37）；`npm run build` 零错误、全量 vitest 106 例通过、旧术语静态扫描测试通过。
- **Priority**: high
- **Depends On**: Task 8, Task 9
- **Description**: web/Dockerfile（node:20-alpine 构建 → nginx:alpine）、.dockerignore；nginx.conf（静态、/api 反代 api:8000 + proxy_buffering off + proxy_read_timeout 300s + HTTP/1.1、try_files 兜底）；compose 在后端产出的 docker-compose.yml 上追加 web 服务（8080:80、depends_on api）；`npm run build` + 镜像构建（api 不在线）；全量测试跑一遍；静态扫描（旧术语/业务常数/any 边界）。
- **Acceptance Criteria Addressed**: AC-20, AC-22
- **Test Requirements**:
  - `rule` TR-10.1: build 与镜像构建成功日志；nginx.conf 三要素文本检查；compose config 通过；证据：输出。
  - `rule` TR-10.2: 全量 vitest 通过且无网络真实外呼（mock 边界审计）；证据：输出 + 走读。
  - `rubric` TR-10.3: AC-22 交互完成度 ≥4（对照 SDD §3 所有失败/置灰/确认点清单逐项勾）；证据：覆盖清单。
