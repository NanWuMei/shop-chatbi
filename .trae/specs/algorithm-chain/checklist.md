# 算法问数链路（algorithm-chain）- 验收清单

> 用法：实现逐项推进时勾选；每条都能在 `tasks.md` 找到对应任务与可执行的 Test Requirement。
> 验收依据：`docs/SDD-算法应用.md` v0.4（冲突以它为准）、`docs/测例.md` T01~T15、`docs/metrics-dictionary.md`。
> 总门禁：无网络 / 无 LLM·EMB key / 无数据库进程下，`pytest algorithm` 全绿；本步不真连库、不做页面、不另设计向量存储。

## 一、契约与编排（对应 AC-1/2/14/13）
- [ ] C1. 主图节点顺序与条件分叉与 SDD §1 一致：S2 未命中走 S1→S3→S4→S5→S6→S7→S8；命中走 S1→S2→S6→S7→S8
- [ ] C2. 所有路由只按 ChainState 显式字段（template_hit / lint_passed / action），无解析自然语言的走向判断
- [ ] C3. ChainResult 六 action 与全部字段（answer/clarify/rejection/error/trace/meta）与 SDD §6 逐字段一致
- [ ] C4. 一个 ChainResult 恰好一个载荷非空；chart、rate_delta 可 null
- [ ] C5. 空结果 = answer（rows=[]、chart=null、「该范围无数据」语义 insight、caliber 照给），不是拒答
- [ ] C6. 目录与 SDD §5 模块树一一对应；边界铁律静态检查通过（Coder 不持执行工具；Writer/Presenter 不碰 SQL/库；Understand 不做授权；节点只传强类型）
- [ ] C7. 双档：Understand/Writer=fast、Aligner/Coder=strong，缺档回落 LLM_MODEL；无 key 可 import、可 build 图，问数才报 E_LLM_UNAVAILABLE；代码无厂商名

## 二、各节点行为（对应 AC-3~11）
- [ ] C8. S1：归因/预测/闲聊 → not_answerable(NOT_DATA_QUESTION)，文案「不算原因、可给相关数据」+ suggestions；LLM 故障重试 1 次后 error(E_LLM_UNAVAILABLE, retryable=true)
- [ ] C9. S2：空库/抽不齐/模板外新约束 → 未命中走 S3 且无 error；填满命中 → 跳 S3/S4/S5 直执行，trace.template_hit=true；全程不调 LLM
- [ ] C10. S3：L0 schema_blocks 必有；L1/示例有则返回（top3~5）；EMB 缺失或失败 → mode=lexical 且 trace 标注；L0 为空时空上下文不崩；检索只作上下文不作授权
- [ ] C11. S4：美妆多候选（仅靠 L0 层级/枚举，无 L1）→ clarify(METRIC_DIM_AMBIGUOUS)；缺时间 → clarify(MISSING_TIME/time_quick)；指代失败 → clarify(ANAPHORA_UNRESOLVED)；问法泛 → clarify(VAGUE)
- [ ] C12. S4：无对应表列 → not_answerable(NO_MATCHING_DATA)；类目级转化率 → not_answerable(CALIBER_CONFLICT)+渠道口径建议
- [ ] C13. S4 无 L1 时：依 L0 列名/注释对齐，口径在 caliber 明示；T06 明示 AOV 分母＝支付订单数；档期归一结果可见（无日历时标注推断）
- [ ] C14. S5 lint：表白名单按 L0、列归属、仅单条 SELECT（禁多语句/DDL/DML）、LIMIT 自动注入（500/上限 1000）四项各有反例测试
- [ ] C15. S5：lint 不过带原因回炉，最多 2 轮；超轮 → query_gen_failed(GEN_LINT_EXHAUSTED)；通过 SQL 的 lineage 表/列全 ∈ L0
- [ ] C16. S6：只经注入的 QueryRunner；超时 → QUERY_TIMEOUT、执行异常 → QUERY_ERROR；0 行照常出 answer；包内无真实驱动连接代码
- [ ] C17. S7：排名→bar；趋势→line/trend_line；对比→grouped_bar/trend_line；占比→pie；单标量/空→chart=null；TableData 与 ChartSpec 字段齐备
- [ ] C18. 对比 changes 由代码 Decimal 计算：金额 2 位、率 1 位；缺段/分母 0 → rate_delta=null（不可比）；无 float 参与业务运算
- [ ] C19. S8：严格一句、只陈述事实（无建议/归因/预测）；数字必须出自真实行或 changes；违规重生成 1 次后模板句兜底、trace 标注，且永不阻断 answer

## 三、澄清与会话（对应 AC-12）
- [ ] C20. clarify 载荷完整（clarify_id/round/title/reason_code/input_type/options/suggestions/allow_custom_text）
- [ ] C21. 澄清确认前不出数：首轮 MockQueryRunner 调用次数 = 0
- [ ] C22. 带 clarified_question + thread_id 重入从 S1 走、checkpointer 恢复槽位；两轮仍未消歧 → not_answerable

## 四、资源与降级（对应 FR-17/18/19）
- [ ] C23. resources 路径缺失/为空 → 视为无增强、不报错；dict/templates YAML 有则加载
- [ ] C24. Writer style_examples.yaml 只控格式、不含业务数字
- [ ] C25. QueryRunner / LLMClient / EmbeddingClient / SchemaProvider / Repository 均为协议注入；本步只给 mock/静态/内存实现，换实现不动链路代码
- [ ] C26. embedding 同文本 5 分钟短缓存生效

## 五、T01~T15 离线回归（对应 AC-15/16）
- [ ] C27. T01~T15 共 15 条场景可逐一点名，全部通过；文案与测例.md 一致
- [ ] C28. T01/T02/T04/T11/T13/T14 等取数类：action=answer 且图型/表/口径符合 SDD §10（T13=pie、T06/T06 类单标量 chart=null、T14 limit=3 且 truncated 行为正确）
- [ ] C29. T03/T12：trend_line 且 T12 承接上文渠道（先有上下文再消解）
- [ ] C30. T07：ComparisonSpec 三段绝对区间 + grouped_bar + changes 正确；T08：mode=yoy、2025 窗口内可答、只陈述方向幅度
- [ ] C31. T05/T09：clarify 且 reason_code=METRIC_DIM_AMBIGUOUS；T10/T15：not_answerable 且 reason_code 分别为 NO_MATCHING_DATA / NOT_DATA_QUESTION
- [ ] C32. 专项路径：S2 命中 vs 空库、lexical 降级、lint 超轮、query 超时/报错、LLM 不可用、空结果、澄清两轮、重入恢复、无 key build、import 边界扫描——齐备且通过

## 六、工程质量（对应 NFR-1~5、AC-17）
- [ ] C33. Python 3.12；async run_chain；依赖锁定 requirements.txt（含/不含 sqlglot 以 OQ-1 批准结论为准）、测试依赖单列
- [ ] C34. 全部测试离线可跑（退出码 0），不依赖商用 API/网络/DB
- [ ] C35. trace 全程累积（path/template_hit/retrieval_mode/lint_rounds/llm_calls/elapsed_ms），不出现在面向用户文案
- [ ] C36. 【rubric ≥4】fixtures 业务保真度：档期区间、美妆多候选、数据故事方向、口径文案可与测例.md / metrics-dictionary 逐条对照
- [ ] C37. 【rubric ≥4】可替换性：生产实现只需按协议注入即可替换全部 mock；提示词/schema/节点三者分离；无「为跑通测例写死的 if/else」

## 七、中段入口（增补，对应 AC-18/19）
- [x] C38. S5 刷新入口：start_at="S5" 从 S5 起跑（trace.path 不含 S1~S4）、不产 clarify、四终态同构（answer/query_gen_failed/query_failed/error）、0 行为空 answer、RetrievalContext 为空时 Coder 按 L0 正常生成、ComparisonSpec 出对比图与 changes（test_task15.py 六用例）
- [x] C39. S4 recalibrate 入口：QueryRunner 调用=0、强制 clarify（round=1、reason_code=METRIC_DIM_AMBIGUOUS、options 按 L0 候选逐项重选、缺时间附 time_quick）、确认后走主链 S1 重入、两轮上限不变（test_task15.py 三用例）
- [x] C40. 兼容性：run_chain 不带新参数时既有 34 用例全部回归通过；ChainResult 契约零变更（后端/前端镜像不受影响）（pytest 46 passed、枚举守卫用例）

## 已批准决议（原 Open Questions，已定）
- [x] OQ-1：同意 lint 引入 sqlglot（已随主链落地）
- [x] OQ-2：requirements 保留 psycopg[binary] 本步不 import
- [x] OQ-3：`algorithm/resources/` 默认留空，业务 YAML 归 P6
