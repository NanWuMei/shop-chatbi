```text
# 10·创建问数评测Skill
一次做完：打分规则写进 Skill 目录，再写 SKILL.md。先不要跑评测。

请帮我创建一条项目 Skill，按下面要求写。不要去参考仓库里可能存在的其它 Skill，按下面自己写。

落点：.trae/skills/eval-chatbi-cases/
  - SKILL.md（必需；YAML frontmatter 含 name、description；正文写何时用/不用、步骤、禁止项、报告）
  - rubric.md（通用打分规则，只解释「期望结果类型」怎么对照返回体；不要把某一份题库写进 Skill）

不要改算法、前端、后端业务代码，不要改 SDD。现在只创建 Skill，不要调用问数接口。

## 这条 Skill 是干什么的
给「已经在本机跑起来的 ChatBI」做问数质量评测，不是测页面好不好用。

做法：调用时由用户指定一份评测文档 → 读出文档里的每一条用例 → 直接打后端 HTTP/SSE 接口 → 用 rubric.md 的硬条件判过/不过 → 写出汇总报告。

用户说「跑问数评测」「按这份文档打分」「出评测报告」时使用。
正在写代码、改 SDD、改评测文档、改打分规则、只在浏览器里点功能时，不要使用。

## 评测文档由调用时指定，不要写死路径
Skill 运行时必须向用户确认评测文档路径（或使用用户这句话里已经点名的文件）。
没有指定就问，不要默认锁死 docs/测例.md，也不要自己另出一套题。
用户指定哪份就读哪份；不增删、不改写问句；也不要去改那份文档。

评测文档建议长这样（缺列就按已有列读，缺「用户问题」或「期望结果类型」就停下来问用户，不要猜）：
- 每条用例：id、用户问题（原句）、期望结果类型
- 期望结果类型常见取值：表 / 图 / 解读 / 表+解读 / 追问（澄清） / 拒答
- 文档里若还有考察点、补充说明、指定澄清选项，当作该条的额外硬条件

docs/测例.md 只是仓库里已有的一份评测文档示例（当前是 T01-T15），格式可以参考，不是唯一来源。

## rubric.md 写通用规则（硬/软分开）
先读 docs/SDD-后端.md 第 3.1、3.2 节（通用约定、问数与澄清的 SSE 帧约定）和 docs/SDD-算法应用.md 第 6 节（ChainResult）；字段形状可对照 web/src/api/types.ts。
接口形态：POST /api/v1/chat/turns（body {session_id?, question}，三态互斥）→ 202 {turn_id, session_id, status:running} → GET /api/v1/chat/turns/{turn_id}/events 收 SSE：零或多个 stage 帧（understanding/checking_caliber/querying）后恰一终态帧 → done。要判的终态帧：answer / clarification / rejection / error。
硬条件不过 = 该条失败。按「期望结果类型」对照终态帧，不要按某几个 T0x 编号写死。

- 表：终态 answer，table.rows 非空
- 图：终态 answer，chart 非空（type ∈ bar/line/trend_line/grouped_bar/pie）
- 解读：终态 answer，insight 非空；若同时有 table，解读里的关键数字应能对上本次 table
- 表+解读：table 与 insight 都要有；解读不做因果归因（文档若写了「不要归因」则作为该条硬条件）
- 追问 / 澄清：先 POST /chat/turns 问原句，期望终态 clarification（status=pending，且无 table/chart/insight）。再 POST /chat/turns {session_id, clarify:{clarify_id, selection:{type:"option"|"time_preset"|"custom", value}}}。文档该条若写了选哪个口径就用哪个；没写就问用户选哪一项，不要擅自改产品开关。第一步若直接出数，该条失败
- 拒答：终态 rejection（reason_code ∈ NOT_DATA_QUESTION / NO_MATCHING_DATA / CALIBER_CONFLICT / GEN_LINT_EXHAUSTED / QUERY_TIMEOUT / QUERY_ERROR），无表无图，不能出现编造数字，reason_text 要人话。QUERY_TIMEOUT / QUERY_ERROR 属故障态重试，判「未通过」并在备注标注与业务拒答区分

某条在评测文档里写了更细的要求（例如必须 Top3、必须相对 8%、必须分渠道、必须承接上一问），以该条文档为准，叠加在上面的类型规则上。多轮/承接类用例沿用同一条返回的 session_id 连问。

软条件只写进报告备注，不单独判失败：解读是否好懂、图类型是否和某份方案完全一致、模板是否命中、检索是 hybrid 还是 lexical。

澄清是链路内建行为，没有 CLARIFY_ENABLED 开关；有澄清类用例也不需要任何前置开关。

## 前置（缺一就停，向用户问，不要猜）
- 本次使用的评测文档路径
- 后端已启动，默认 [http://127.0.0.1:8000](http://127.0.0.1:8000)（用户另给了地址就用用户的）
- GET /api/v1/health：checks.db=ok 且 checks.llm=ok（整体 status=ok；embedding=unconfigured 不卡，检索会走 lexical 降级）

否则不要开跑。

## 执行步骤
1. 读本 Skill 的 rubric.md
2. 健康检查
3. 按文档逐条：POST /api/v1/chat/turns，question 用该条用户问题原文；不带 session_id 自动建会话，多轮/承接类沿用上一条返回的 session_id
4. GET /api/v1/chat/turns/{turn_id}/events 收流到终态帧
5. 期望为追问/澄清的：ask → clarify 两步，按 rubric 和该条文档
6. 单条超时从宽（问数可能几十秒）；一条失败记下 HTTP 状态、body 摘要或 error/rejection 帧，继续下一条，不要中断整场
7. 硬条件全过才算该条通过；软条件进备注
8. 写报告（条数以这份文档为准，不要写死 15 条）

禁止：改代码 / 改 YAML 字典 / 改 SDD / 改用户指定的评测文档 / 改 rubric；手写答案 SQL；打开浏览器测前端；把 LLM/EMB 配置换成假实现、补表、为过题改口径；测报表、登录、Compose。

## 报告
路径：开发记录/评测报告-YYYYMMDD.md

开头：用了哪份评测文档、通过条数、失败条数、环境（后端地址、health 检查结果；不要写密钥）

表：id、问句、期望、实际终态帧、硬条件过/不过、备注

失败条用人话写可能卡在出数 / 澄清 / 拒答 / 执行失败，不要给代码补丁，不要把完整返回体粘进报告。

创建完成后告诉我 Skill 路径，并说明：不会每次开聊自动加载；要用时点名这条 Skill，并告诉它评测文档是哪一份。
```
