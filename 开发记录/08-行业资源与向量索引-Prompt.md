# 08 · 行业资源与向量索引 Prompt（L0/L1/模板/示例 / pgvector）

五轮分开做，一轮确认后再贴下一轮。L0 抽取与 pgvector exemplar 表/检索协议已在后端实现（backend_service），第 1、4 轮以验证与补缺为主，第 2、3 轮只产出 YAML 资源。不改算法链路代码，不写 SQL 生成代码。

---

## 第 1 轮 · 验证 L0 已从真实 dw schema 抽取（后端已实现，本轮不重写）

```text
算法、后端都已完成开发。L0 不再是 Mock：backend_service/data/schema_provider_pg.py 会在启动序列里从 dw schema 抽表/列/类型/主外键/中文注释/枚举采样并进程内缓存。本轮只做真库验证与缓存开关确认，不要重写抽取器、不要改算法链路、不要建向量表、不要写 L1 YAML、不要做问数。

先读：
- docs/SDD-后端.md 第 4.1、5.1、5.2 节
- docs/SDD-算法应用.md 第 7.1 节
- backend_service/data/schema_provider_pg.py
- backend_service/composition.py（startup_sequence）

验证清单：
1. 后端启动后 L0 能列出 dw 全部业务表的表名、列名、列类型、主外键、中文注释；不混入 app、public 表
2. 枚举采样：text 列 DISTINCT ≤20 才收录；「美妆」经 enum_candidates 能命中 ≥2 个候选（T09 澄清前提）
3. META_SCHEMA_CACHE_ENABLED=true 时，启动能把 L0 落 app.meta_schema_cache；false（默认）时仅进程内缓存
4. 库不可达时的启动行为：L0 属必需、报错要能看清；exemplar 等可选增强失败只降级不退出

交付：
- 验证脚本或日志，证明 L0 来自真实 dw schema、无 app/public 混入
- 一份说明：哪些已接上、哪些仍缺

人审：有没有重写抽取器绕开后端实现；L0 是否真实来自 dw；枚举采样上限是否仍是 20。
```

---

## 第 2 轮 · 按 L0 出 L1 业务字典（YAML，人审后才算数）

```text
L0 已验证。现在只做 L1 业务语义字典，不做向量，不做导入，不改算法链路。

先读：
- docs/metrics-dictionary.md
- docs/SDD-算法应用.md 第 7.1 节（资源文件怎么存）
- algorithm/resources/loader.py（dict 目录按文件名识别 metrics/entities/calendar）
- 第 1 轮确认的 L0 清单

目标：基于 L0 把业务字典补成「能给模型参考的最小 L1」，落 algorithm/resources/dict/。

约束：
1. 这是通用 ChatBI，不绑定行业词典。
2. 基于 L0 出 L1，包含指标、维度、口径公式、实体映射；按 loader 约定拆 metrics.yaml、entities.yaml、calendar.yaml。
3. 指标覆盖 metrics-dictionary v0.2 拍板的唯四指标：GMV、支付转化率（支付买家数÷访客数）、退货率、AOV；可另加新老客 GMV 占比等派生展示口径。
4. 维度至少覆盖：渠道、类目、档期、日期、新老客。
5. 口径公式必须明确分子/分母（以 metrics-dictionary v0.2 §2 为准）：
   - 支付转化率 = 支付买家数（去重客户）/ 访客数（UV）；本版不支持类目粒度转化率
   - GMV = 支付状态订单的商品成交金额合计（不含运费、不扣退款退货）
   - 退货率 = 退货商品成交金额 / GMV
   - AOV = GMV / 支付订单数（分母口径写死一种，与测例 T06「口径摘要明示」一致）
6. calendar.yaml 落档期窗口（{档期名: [start, end]}）：
   - 今年 618 正式期 = 2026-06-16~2026-06-18；去年同窗 = 2025-06-16~2025-06-18
   - 预热期 = 2026-06-01~2026-06-15；返场 = 2026-06-19~2026-06-20（去年 2025 同窗）；「618大促期间」整体命名区间 = 当年 6/1~6/20
   - 大促前一周 = 2026-06-09~2026-06-15；大促后一周 = 2026-06-19~2026-06-25
7. 不要改算法链路；L1 只作为模型参考，不做运行时硬闸门。
8. 不要改数据库；L1 是静态 YAML，不自动同步表结构；实体映射必须能在 L0 中找到对应表/列。

交付：
- L1 YAML 三件，按指标、维度、口径、实体组织
- 一份对照表：YAML 里的每个指标/维度是否能在 L0 中找到对应表/列

人审：指标公式是否与测例一致；是否混入未在 L0 中出现的表/列；是否误写成 SQL 生成代码。
```

---

## 第 3 轮 · 模板库 + 示例种子（仍是 YAML，SQL 只作为 few-shot）

```text
L1 已入库。现在只做模板库和示例种子，不做向量导入，不改算法链路。

先读：
- docs/SDD-算法应用.md 第 3 节里的 S2（语义缓存/模板）、S3（检索）两小节，以及第 7.1 节
- docs/测例.md
- algorithm/resources/loader.py（templates 目录约定）
- backend_service/data/pg_exemplar_repo.py（Exemplar 字段：question/sql/chart_type/tags）

目标：给高频问法提供模板，给复杂问法提供 few-shot 示例种子。

约束：
1. 模板库用 YAML，落 algorithm/resources/templates/，覆盖排名、趋势、对比、占比、TopN 等常见形态；图型对齐五图型 bar/line/trend_line/grouped_bar/pie。
2. 示例种子用 YAML，每条包含 question、sql、chart_type、tags，作为第 4 轮 exemplar 导入的源；SQL 是给模型参考的写法，不是执行语句。
3. 示例只做 few-shot，不做运行时校验；本轮不调用 Embedding API。
4. 模板和示例都不依赖向量检索，都不硬编码业务逻辑，只做参考资料。

交付：
- 模板库 YAML，覆盖至少 5 类问法
- 示例种子 YAML，覆盖至少 5 类问法
- 一份说明：模板在 S2、示例在 S3 分别怎么被算法参考

人审：SQL 是否仅作为 few-shot；是否误将示例当作执行代码；是否引入向量检索。
```

---

## 第 4 轮 · exemplar 种子导入与向量检索验证（表和索引后端已自动建）

```text
YAML 已就绪。exemplar 表、hnsw 索引、维度校验、向量/词命中两路检索都已在后端实现（backend_service/storage/ddl.py + data/pg_exemplar_repo.py；启动序列在 EMB_* 齐全时自动 ensure）。本轮只做种子导入与检索验证，不要另建向量表、不要改算法链路、不要动业务数据。

先读：
- docs/SDD-后端.md 第 4.1、7.3、7.4 节
- backend_service/storage/ddl.py（exemplar_ddl）
- backend_service/data/pg_exemplar_repo.py

前置：
- EMB_BASE_URL / EMB_API_KEY / EMB_MODEL / EMB_DIM 可用（向用户要，密钥走环境变量，不写死）
- 在 Supabase 幂等执行一次：CREATE EXTENSION IF NOT EXISTS vector; CREATE SCHEMA IF NOT EXISTS app;（dw 业务数据不要动）

做：
1. 写一次性导入脚本：读第 3 轮示例种子 YAML → 调 Embedding API 向量化 → 经 repository.upsert_exemplar 落 app.exemplar（source=seed；维度必须等于 EMB_DIM，不符会被 AC-16 校验拦下）。表若还不存在，脚本可先跑 exemplar_ddl（幂等 ensure），不必整站启动
2. 验证向量检索：对若干问句 embedding 后 search_exemplars，能召回对应示例并给出分数
3. 验证词命中降级：不传 embedding、只传 keywords 也能召回
4. 幂等：重复导入不产生重复行

交付：
- 导入脚本
- 检索验证结果（召回的 top 示例与分数）
- 一段说明：为什么不需要手写向量表 DDL（哪段启动序列/DDL 函数负责）

人审：是否只索引示例问句；有没有动业务数据；有没有绕开 upsert_exemplar 自建表。
```

---

## 第 5 轮 · 只验证资源是否接上，不跑测例问句

```text
L0、L1、模板、示例种子、向量检索已就绪。现在只验证「资源能否被算法访问」，不跑完整问数链路，不改算法。

先读：
- docs/SDD-算法应用.md 第 7.1 节
- docs/SDD-后端.md 第 4.1、5.2 节

验证清单：
1. L0 能列出 dw 业务表、列、类型、注释，不包含 app、public
2. L1 dict（metrics/entities/calendar）能被 loader 加载，实体与 L0 对应
3. templates 能被加载，SQL 仅作为 few-shot
4. app.exemplar 存在且含种子，向量与词命中两路都能召回
5. 算法经后端装配（或等价验证脚本）能访问全部资源，不需要真实执行业务 SQL

交付：
- 资源加载验证报告
- 向量检索验证结果
- 一份说明：哪些资源已接上，哪些仍未接上

人审：有没有写成 T01-T15 业务 SQL；有没有把 L0 改回 Mock；向量检索是否真实工作。
```
