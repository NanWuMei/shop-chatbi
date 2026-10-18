# 问数评测打分规则（rubric）

通用打分规则：只解释「期望结果类型」如何对照接口返回体，不绑定任何一份具体题库。
字段形状权威来源：docs/SDD-后端.md 第 3.1、3.2 节（通用约定、问数与澄清的 SSE 帧约定）、docs/SDD-算法应用.md 第 6 节（ChainResult）；前端镜像见 web/src/api/types.ts。

## 接口与帧（判定对象）

- POST /api/v1/chat/turns，body 三选一互斥：
  - 新问题 `{session_id?, question}`（不带 session_id 自动建会话）
  - 澄清确认 `{session_id, clarify:{clarify_id, selection:{type, value}}}`
  - recalibrate 重新澄清不在评测范围
  响应 `202 {turn_id, session_id, status:"running"}`
- GET /api/v1/chat/turns/{turn_id}/events 收 SSE：零或多个 stage 帧（understanding / checking_caliber / querying）→ 恰好一个终态帧 → done。
- 参与判定的终态帧：answer / clarification / rejection / error。

**硬条件不过 = 该条失败。** 按「期望结果类型」对照终态帧，不按某几个用例编号写死。

## 硬条件（按期望结果类型）

### 表
- 终态帧 answer
- table.rows 非空

### 图
- 终态帧 answer
- chart 非空，type ∈ bar / line / trend_line / grouped_bar / pie

### 解读
- 终态帧 answer
- insight 非空
- 若同时返回 table：解读里的关键数字应能对上本次 table

### 表+解读
- table 与 insight 都非空
- 解读不做因果归因；评测文档该条若写了「不要归因」，作为该条硬条件

### 追问 / 澄清（两步）
1. 先 POST /chat/turns 问原句，期望终态 clarification：
   - clarify.status = pending
   - 无 table / chart / insight（澄清终态本轮不执行任何查询）
   - 第一步若直接出数，该条失败
2. 再 POST /chat/turns `{session_id, clarify:{clarify_id, selection:{type, value}}}`：
   - selection.type ∈ option | time_preset | custom；option / custom 的 value 为字符串，time_preset 的 value 为预设 key 或 {start,end}
   - 文档该条写了选哪个口径就用哪个；没写就问用户选哪一项，不要擅自替用户决定
   - session_id 沿用第一步返回的
   - 确认后的终态按该条文档判；文档未细写时，默认期望正常出数（answer）
- 非澄清类用例若补充说明要求「先澄清再出结果」，同样先走这两步，再按该条期望结果类型判最终终态

### 拒答
- 终态帧 rejection，reason_code ∈ NOT_DATA_QUESTION / NO_MATCHING_DATA / CALIBER_CONFLICT / GEN_LINT_EXHAUSTED / QUERY_TIMEOUT / QUERY_ERROR
- 无表无图，不得出现编造数字
- reason_text 是大白话业务文案（不暴露 SQL / 堆栈 / 技术码）
- QUERY_TIMEOUT / QUERY_ERROR 是故障态而非业务拒答：判「未通过」，并在备注标注与业务拒答区分

## 条目级附加硬条件

评测文档某条写了更细要求（如必须 Top3、必须相对 8%、必须分渠道、必须承接上一问），以该条文档为准，叠加在上述类型规则上。多轮/承接类用例沿用同一条返回的 session_id 连问。

## 软条件（只写进报告备注，不单独判失败）

- 解读是否好懂
- 图类型是否与某份方案完全一致
- 模板是否命中、检索是 hybrid 还是 lexical（对应 ChainResult.trace.template_hit / trace.retrieval_mode；本版 SSE 帧不含 trace，接口侧取不到就在备注写「不可见」，不算失败）

## 其它

- 澄清是链路内建行为，没有 CLARIFY_ENABLED 开关；有澄清类用例也不需要任何前置开关。
