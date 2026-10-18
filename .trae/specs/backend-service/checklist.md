# 后端服务（backend-service）- 验收清单

> 依据：`docs/SDD-后端.md` v0.2（冲突以它为准）、`docs/SDD-算法应用.md` v0.4（只消费不重写）、`docs/PRD.md` F1~F9。
> 总门禁：离线单测（无 DB/key/网络）全绿；integration 在本地 db 容器全绿；不做前端页面、不重做算法步骤、不产 dw 业务 DDL/seed（P6）。
> 状态说明（2026-10-17）：`[x]` = 离线单测/走读已验证（`pytest algorithm backend_service/tests` → 146 passed, 25 deselected, exit 0）；标注「待人工 OQ-2」的项需在有 Docker 的环境执行 `docker compose up -d db` 后 `pytest backend_service/tests -m integration` 留输出（本机无 Docker，集成测试已通过收集验证、未经真实 db 运行）。

## 一、接口契约（§3）
- [x] B1. Base path `/api/v1`；统一错误信封；§8 错误码→HTTP 映射全部可达（E_VALIDATION/E_TURN_NOT_FOUND/E_NOT_FOUND/E_NAME_CONFLICT/E_CLARIFY_EXPIRED/E_REPORT_NOT_SAVEABLE/E_LLM_UNAVAILABLE/E_INTERNAL）——注：映射表驱动单测 test_config_errors.py + 404 信封
- [x] B2. POST /chat/turns 三入参（question / clarify / recalibrate）互斥；成功 202 running；空/超长/不互斥 400；票据失效 409；源 turn 缺 404
- [x] B3. SSE：stage 三行映射写死（S1=understanding；S2/S3/S4=checking_caliber；S5/S6/S7/S8=querying），同段去重；建流 404——注：STAGE_BY_NODE 全等断言 + on_event 驱动真实映射路径
- [x] B4. 终态五帧映射正确：answer / clarification / rejection（三类 action 六 reason_code）/ error / cancelled，帧后恒 done；空结果是同构 answer
- [x] B5. AnswerEvent 五业务字段逐字镜像 ChainResult.answer，仅多信封字段；saveable=answer 且 rows 非空；data_time_range/queried_at 正确派生
- [x] B6. cancel：202 cancelling → cancelled 帧 + note 消息；重复取消不 500——注：含任务未启动即取消的竞态兜底（cancel_requested 自查）
- [x] B7. 事件缓冲 10 分钟、Last-Event-ID 尽力补帧——注：FakeClock 单测过期/续帧

## 二、澄清与落库（F2/§3.3）
- [x] B8. 澄清确认前 FakeQueryRunner 调用次数=0；clarification 消息带 status（pending/confirmed/cancelled）
- [x] B9. option/time_preset/custom 三种 selection 拼出 clarified_question 并从 S1 重入；重复确认 409
- [x] B10. messages：user/终态消息 seq 会话内递增；stage 不落库；internal 落 {sql,trace,query_spec}——注：真实 PG 的 seq 唯一约束/级联由 B22 集成联跑复验（OQ-2）
- [x] B11. 所有出前端报文（SSE/会话还原/列表/报表）grep 不到 sql、trace、query_spec（及 narrative、dual_line 旧字段）——注：静态扫描 + 各路由单测双重覆盖

## 三、会话（F7）
- [x] B12. 列表按 last_question_at 倒序、分页默认 0/50；title=首问；message_count 正确——注：真实 PG 行为由 B21/B22 集成联跑复验（OQ-2）
- [x] B13. 会话还原按 seq 完整（含澄清最终状态/拒答/note）；删除级联 204；404 正确——注：级联由 B22 集成复验（OQ-2）

## 四、报表（F5/F6）
- [x] B14. 保存只认服务端落库 answer；非 answer/空结果 → 409 E_REPORT_NOT_SAVEABLE
- [x] B15. 同名 409 E_NAME_CONFLICT 带 existing；overwrite 事务更新、id 不变；字段缺失整体回滚；新存 201——注：缺字段回滚的接口级单测已过；真实 PG 事务回滚由 B22 集成复验（OQ-2）
- [x] B16. 列表名称包含匹配+倒序；改名空名 400/同名 409；删除 204
- [x] B17. GET 报表直读快照：run_chain 调用=0、analytics 连接=0、不走 S5/澄清——注：spy 单测 chain_runner.calls==[] 且 connect_count==0
- [x] B18. refresh 调算法 S5 刷新入口（不走 S1~S4、不重新澄清）；四终态同构返回；不落消息、不改快照——注：_assert_s5_seam 断言 start_at="S5" 接缝
- [x] B19. continue-session 写 inherited_spec=query_spec、无假消息；首问 conversation_summary 含继承口径；报表不变

## 五、健康与生命周期
- [x] B20. /health 聚合规则：llm unconfigured/error → degraded；embedding unconfigured 不降级；db/llm/embedding 三态正确——注：六组聚合表驱动 + 探针异常隔离
- [x] B21. 启动序列：create_all 幂等 → L0 抽取 → EMB 齐全才 ensure exemplar+hnsw；无 LLM key 服务照常启动，提问走 SSE error(E_LLM_UNAVAILABLE,retryable=true)——注：启动序列真实 db 路径（test_startup_health.py）待人工 OQ-2 复验；lifespan 钩子离线路径已验证

## 六、数据层与安全（§5/§6，integration）
- [ ] B22. app_user 仅 app schema DML；chatbi_ro 对 dw 仅 SELECT，写/建表/读 app 均被 PG 拒绝——待人工 OQ-2：`docker compose up -d db` 后 `pytest backend_service/tests -m integration::test_permissions.py` 留输出
- [ ] B23. QueryRunner：单条 SELECT 守卫（多语句/写操作执行前拒绝）、statement_timeout=10s（pg_sleep 实证超时）、行限幅 1000 + truncated 回传——注：守卫/截断离线单测已过；pg_sleep 超时实证待人工 OQ-2（test_query_runner_integration.py）
- [ ] B24. L0 真实抽取：夹具六表的表/列/类型/主外键/中文注释齐；枚举含美妆四候选、档期四值——待人工 OQ-2（test_l0_extraction.py）
- [ ] B25. exemplar：未配 EMB 不建表不报错；配齐后 vector 列+hnsw、upsert/topN 检索、EMB_DIM 校验——待人工 OQ-2（test_exemplar_repository.py）
- [x] B26. 所有面向用户文案业务化，不含 SQL/堆栈/技术码——注：note/报错文案单测断言 + 走读

## 七、部署（F9，本步范围）
- [ ] B27. init SQL 幂等：两 schema、两角色授权、CREATE EXTENSION vector；不含 dw 业务表 DDL/seed——注：文件内容走读通过；真实执行待人工 OQ-2（dw_test.sql 夹具不属业务 seed）
- [ ] B28. api 镜像同装 backend_service/+algorithm/，uvicorn 单 worker；.env.example 全量、.env 不提交——注：文件走读通过；镜像构建待人工 OQ-2
- [ ] B29. compose 仅 db/api 两服务（本步不含 web 块，已拍板，web 由前端轮次补）；api 依赖 db healthy 起后 /health 可达；`down -v && up` 干净重置——待人工 OQ-2：`docker compose config && docker compose up -d db api` 冒烟 /health
- [x] B30. 分层 import 静态扫描：api 不直调 run_chain；algorithm 不 import storage/连接串；写只走 APP 引擎；后端无算法内部实现改动——注：test_static_scan.py AST 白名单 + algorithm 包零改动
- [ ] B31. 清空 LLM/EMB env、无 DB 下离线单测退出码 0；integration 集在 db 容器一次跑绿——注：离线半已达成（146 passed, 25 deselected, exit 0）；integration 半待人工 OQ-2
- [x] B32. 【rubric ≥4】AC-19 分层纪律；【rubric ≥4】AC-20 离线测试可独立性——注：TR-12.4 依据 AST 扫描白名单 + 分层走读；TR-12.5 依据用例清单（除 `-m integration` 外全部用例无 DB/key/网络依赖，146 例 exit 0）

## 已拍板决议（原 OQ-1~OQ-5，已定，不再是开放项）
- [x] OQ-1：本步 compose 不含 web 块；web 由前端轮次补齐并首次达成三服务 F9
- [x] OQ-2：集成测试 Done = 人工 `docker compose up db` 跑一次 integration 留输出；CI 不属本版
- [x] OQ-3：messages.internal 落 {sql, trace, query_spec} 三键，仅服务端可见
- [x] OQ-4：先补算法再做后端——algorithm-chain 增补轮次先行交付 S5 刷新 / S4 recalibrate 两入口（测试全绿），后端才开始编码、不做 stub 顶位
- [x] OQ-5：常数默认落定（问题 500 字，依前端 SDD §3.1 统一 / 分页 50 上限 200 / SSE 缓冲 10min / 口径摘要 5 轮）
