# 前端页面（frontend-pages）- 验收清单

> 依据：`docs/SDD-前端.md` v0.2（冲突以它为准）；报文以后端 SDD §3、字段以算法 SDD §6 ChainResult 为准。
> 总门禁：`npm run test`（vitest，jsdom，无真实网络/无 api/db）全绿；`npm run build` 零错误；web 镜像可构建；不新发明接口、不做后端/算法改动。
> 验收结论（2026-10-17）：vitest 13 文件 106 用例全绿；`npm run build` 零错误；旧术语静态扫描测试常驻通过。F35~F37 镜像构建本机无 Docker，文本审查通过、真机构建留人工（OQ-2）。

## 一、类型与契约
- [x] F1. api/types.ts 逐字镜像：Action 联合、AnswerEvent（table/chart/insight/caliber/comparison + 信封 6 字段）、ClarifyPayload（四 reason_code/三 input_type）、RejectionPayload（六 reason_code）、ErrorPayload、stage 三值、HTTP 错误信封（evidence：types.test.ts + fixtures 类型校验；delta 为字符串等以算法 §6 实现为准）
- [x] F2. 图型枚举仅 bar/line/trend_line/grouped_bar/pie 且 chart 可 null；全仓 grep 无 narrative、dual_line（evidence：types.test.ts 静态扫描用例常驻）
- [x] F3. 终态/reason_code 分发为穷尽 switch（新增联合成员编译失败的守卫留证）（evidence：api/guard.ts assertNever + MessageEntry 穷尽 switch + 枚举守卫测试）
- [x] F4. 契约 fixtures 覆盖：五型图、空结果、对比（rate_delta=null）、truncated、澄清×三控件、拒答×六码、error、cancelled、SSE 帧序列、409/400/502、报表刷新四态（evidence：src/test/fixtures/ 四组文件 + 类型校验通过）

## 二、骨架与路由
- [x] F5. `/`→/chat；五路由可达，未知路由兜底；顶栏三入口（问数/报表/对话记录），默认问数（evidence：router.test.tsx）
- [x] F6. 切走再回问数页，当前会话与输入不丢（Zustand 保活）（evidence：router.test.tsx TR-4.1/TR-4.2）
- [x] F7. RequireAuth 包装位直接放行；client 拦截器位存在但不注入 token；无任何登录/账号 UI（evidence：router.tsx + client.ts 走读 TR-3.3）

## 三、问数与 SSE
- [x] F8. 空置灰；500 字边界（500 可发、501 置灰+固定提示，不发请求）；回车发送、Shift+回车换行；乐观用户气泡（evidence：Composer.test.tsx + chatStore.test.ts）
- [x] F9. 两段式：POST 202→EventSource；三阶段固定文案/三态（✓/转圈/灰）、同段去重；done 关流（evidence：sse.test.ts 脚本化帧）
- [x] F10. 取消：调 cancel→cancelled 帧→"已取消"静态文本，无半成品卡；cancel 失败静默（evidence：MessageEntry.test.tsx）
- [x] F11. 断线重连带 Last-Event-ID；连续 2 次失败→"连接中断，重试"；全程不重复 POST 问题（evidence：sse.test.ts 重连用例）
- [x] F12. 卸载/切换关旧流；回会话靠落库消息还原，不补演过程动画（evidence：chatStore closeStream + loadSession 用例）
- [x] F13. 问完一轮 URL 就地变 /chat/:sessionId；追问只带 session_id，前端不缓存/回传口径（evidence：AskPage onSessionReady→navigate replace 走读）

## 四、终态与卡片
- [x] F14. 六终态分发正确（ResultCard/EmptyResult/ClarifyCard/RejectMessage/ErrorMessage/已取消）（evidence：MessageEntry.test.tsx 参数化六终态）
- [x] F15. EmptyResult：insight 无数据句 + 口径折叠；无图、无空表、无保存入口（evidence：MessageEntry.test.tsx）
- [x] F16. ResultCard 五区顺序固定：insight→chart→table→caliber→操作（evidence：组件结构走读）
- [x] F17. 表格：label 列名、format（千分位/%）、分页 20/50/100、truncated 横幅"仅展示前 {display_limit} 行"、tooltip 显值（evidence：MessageEntry.test.tsx answerComparison 用例）
- [x] F18. 图：五型 mapper 纯函数；chart=null 不渲染图区且不调 mapper；切换菜单仅列 switchable 且切换零网络；ErrorBoundary 降级"图表暂不可用"（表/解读照显、保存置灰）（evidence：mapper.test.ts + 切换 mock 计数用例）
- [x] F19. 对比：value_delta/rate_delta 普通字段渲染；null 显"不可比"非 0/∞；insight 原样不追加归因（evidence：MessageEntry.test.tsx）
- [x] F20. 澄清：三控件正确；未选确认置灰；确认请求体 clarify 结构；suggestions 点选直接发问；取消就地收起不发请求；custom 换问法；round 只显服务端值；卡面无数字/无保存（evidence：ClarifyCard.test.tsx）
- [x] F21. 「口径不对，重新澄清」发 recalibrate{source_turn_id}，原卡保留（evidence：chatStore.recalibrate + ResultCard Actions 走读）
- [x] F22. 拒答六码：四业务码用 reason_text+suggestions 无重试样式；QUERY_TIMEOUT/QUERY_ERROR 故障态+重试（原问题重发）；无码值/SQL/lint/堆栈外露（evidence：MessageEntry.test.tsx 六码参数化）

## 五、报表
- [x] F23. 保存可点＝saveable 且图表未降级；五态置灰 Tooltip 文案逐一正确（evidence：saveable.test.ts 表驱动）
- [x] F24. 弹窗：按问题预填/可改/空名去空格拦截；口径只读行；缩略图随 chart null 显隐（evidence：SaveReportDialog/index.test.tsx）
- [x] F25. 保存成功→关弹窗+"已存为报表：《名称》"+列表链接；409 三选一（覆盖 overwrite=true/换名/取消）；其他错误 message.error（evidence：SaveReportDialog/index.test.tsx 409 三分支请求体）
- [x] F26. 列表：名称/时间/口径摘要按序；q 搜索防抖 300ms；改名行内编辑（回车/PUT、Esc 撤、空名拦截、409 提示、失败回滚）；删除二次确认固定文案、失败行恢复（evidence：reportStore.test.ts rename/remove；改名 409 走 store 错误 toast，见 tasks.md Task 8 注记）
- [x] F27. 查看页：仅 GET 直渲 snapshot（无过程态/澄清）；显示数据时间与取数时间；chart=null 无图区（evidence：reportStore.test.ts + ReportViewPage 走读）
- [x] F28. 刷新：answer 临时替换+"未保存"标记且不调保存接口；空结果走 EmptyResult；query_failed 区内超时/失败+重试；query_gen_failed 业务文案；口径区与继续问始终在；不用旧数冒新数（evidence：reportStore.test.ts 刷新四态+快照不变）
- [x] F29. GET 详情失败：保留页头与名称+"加载失败＋重试"，不白屏；continue-session 成功跳 /chat/{sessionId}，失败 message.error（evidence：ReportViewPage 走读 + reportStore.test.ts）

## 六、对话记录
- [x] F30. 列表首问标题/最近时间/条数、倒序、分页；打开按 seq 用同一渲染器还原五 type，还原后可追问（evidence：chatStore.test.ts loadSession + TR-9.2 import 扫描）
- [x] F31. 删除二次确认→DELETE→回列表；界面无全文搜索/收藏/跨设备入口（evidence：SessionsPage 走读）

## 七、工程与部署
- [x] F32. strict TS，any 仅限测试 mock 边界；vitest 全绿且无真实网络外呼（evidence：tsconfig strict/noUnusedLocals；106 例全绿；mock fetch/EventSource 边界审计）
- [x] F33. 前端零业务计算：除 format 格式化外无数值推导（【rubric AC-21 ≥4】）（evidence：mapper 数值直取 rows 零计算走读 + grep）
- [x] F34. SDD §3 所有失败/置灰/确认点均有可观察落点（【rubric AC-22 ≥4】）（evidence：覆盖清单走读，见 tasks.md Task 10）
- [x] F35. Dockerfile 多阶段（node:20-alpine→nginx:alpine），构建不需 api/db 在线（evidence：web/Dockerfile 文本审查；实际落地 node:22-alpine 构建→nginx:1.27-alpine，本机无 Docker，镜像构建留人工 OQ-2）
- [x] F36. nginx：静态托管 + /api 反代 api:8000（proxy_buffering off、proxy_read_timeout 300s）+ try_files SPA 兜底（evidence：web/nginx.conf 三要素文本检查）
- [x] F37. compose web 服务 8080:80、depends_on api（在后端产出的 docker-compose.yml 上追加，三服务首次齐备）（evidence：docker-compose.yml web 块 127.0.0.1:8080:80 + depends_on api；api 改 expose 内网对齐 SDD-后端 §10）
- [x] F38. /health 弱探测：degraded 非阻断提示，探测失败不阻塞（evidence：ReportViewPage /health 弱提示按 OQ-4）

## 已拍板决议（原 Open Questions，已定）
- [x] OQ-1：问题长度统一 500（前端 SDD §3.1 为准，后端 spec 已跟随修正）
- [x] OQ-2：本步 Done = 离线测试 + build + 镜像/nginx 审查；真机端到端留三服务齐备后统一验收
- [x] OQ-3：在后端产出的 compose 上追加 web 块（后端本步不含 web 块）
- [x] OQ-4：/health 首屏弱探测默认做
