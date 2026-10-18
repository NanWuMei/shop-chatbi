-- ============================================================================
-- ChatBI 集成测试 dw 种子库（api/tests/fixtures/dw_test.sql）
-- 用途：B22 权限 / B23 QueryRunner / B24 L0 抽取 的真实库验收（OQ-2 人工跑）。
-- 形状依据 docs/metrics-dictionary.md §5 六表大纲 + §3.1 美妆四候选 + §4.1 档期；
-- 这是测试资产（P6 生产 DDL/seed 另行产出），DROP/CREATE/INSERT 幂等重建，可反复执行。
-- 全部取模伪随机：无 random()，多环境可复现。
-- 以 postgres 超级用户执行（集成 conftest 自动执行）。
-- ============================================================================
BEGIN;

DROP TABLE IF EXISTS dw.fact_traffic_daily CASCADE;
DROP TABLE IF EXISTS dw.fact_order_item    CASCADE;
DROP TABLE IF EXISTS dw.fact_order         CASCADE;
DROP TABLE IF EXISTS dw.dim_category       CASCADE;
DROP TABLE IF EXISTS dw.dim_channel        CASCADE;
DROP TABLE IF EXISTS dw.dim_date           CASCADE;

-- ---------------------------------------------------------------------------
-- 维度表
-- ---------------------------------------------------------------------------
CREATE TABLE dw.dim_date (
    date                date PRIMARY KEY,
    year                integer NOT NULL,
    month               integer NOT NULL,
    day                 integer NOT NULL,
    promo_phase         text    NOT NULL,
    is_promo            boolean NOT NULL,
    promo_relative_week integer
);
COMMENT ON TABLE  dw.dim_date                IS '日期维度：全部时间的归一日轴，含大促档期属性';
COMMENT ON COLUMN dw.dim_date.date           IS '日期（自然日）';
COMMENT ON COLUMN dw.dim_date.year           IS '年份';
COMMENT ON COLUMN dw.dim_date.month          IS '月份（1-12）';
COMMENT ON COLUMN dw.dim_date.day            IS '日（1-31）';
COMMENT ON COLUMN dw.dim_date.promo_phase    IS '档期阶段（预热/正式/返场/日常）';
COMMENT ON COLUMN dw.dim_date.is_promo       IS '是否大促档期日';
COMMENT ON COLUMN dw.dim_date.promo_relative_week IS '相对本期大促正式期的周序（负=前，正=后）';

CREATE TABLE dw.dim_channel (
    channel_id   text PRIMARY KEY,
    channel_name text NOT NULL,
    channel_type text NOT NULL
);
COMMENT ON TABLE  dw.dim_channel                IS '渠道维度：流量与成交来源';
COMMENT ON COLUMN dw.dim_channel.channel_id     IS '渠道编码（CH_A/CH_B/CH_C/CH_D）';
COMMENT ON COLUMN dw.dim_channel.channel_name   IS '渠道名称（渠道A/渠道B/渠道C/渠道D）';
COMMENT ON COLUMN dw.dim_channel.channel_type   IS '渠道类型（自有商城/平台电商/社交电商/线下门店）';

CREATE TABLE dw.dim_category (
    category_id integer PRIMARY KEY,
    level1_id   integer NOT NULL,
    level1_name text    NOT NULL,
    level2_name text    NOT NULL
);
COMMENT ON TABLE  dw.dim_category                IS '类目维度：叶子类目（事实挂叶子）';
COMMENT ON COLUMN dw.dim_category.category_id    IS '叶子类目ID';
COMMENT ON COLUMN dw.dim_category.level1_id      IS '一级类目ID';
COMMENT ON COLUMN dw.dim_category.level1_name    IS '一级类目名（美妆个护/服饰/家居）';
COMMENT ON COLUMN dw.dim_category.level2_name    IS '二级类目名（彩妆/护肤/美妆工具/男装/女装/内衣/家清/家纺）';

-- ---------------------------------------------------------------------------
-- 事实表
-- ---------------------------------------------------------------------------
CREATE TABLE dw.fact_order (
    order_id        bigint PRIMARY KEY,
    customer_id     bigint        NOT NULL,
    channel_id      text          NOT NULL REFERENCES dw.dim_channel (channel_id),
    order_date      date          NOT NULL REFERENCES dw.dim_date (date),
    is_new_customer boolean       NOT NULL,
    pay_status      text          NOT NULL,
    gmv_amount      numeric(12,2) NOT NULL
);
COMMENT ON TABLE  dw.fact_order                 IS '订单事实：一单一行（GMV/AOV/新老客粒度）';
COMMENT ON COLUMN dw.fact_order.order_id         IS '订单ID';
COMMENT ON COLUMN dw.fact_order.customer_id      IS '客户ID（去重计买家数）';
COMMENT ON COLUMN dw.fact_order.channel_id       IS '渠道编码（外键 dim_channel）';
COMMENT ON COLUMN dw.fact_order.order_date       IS '下单日期（外键 dim_date）';
COMMENT ON COLUMN dw.fact_order.is_new_customer  IS '是否新客（新客/老客刻画）';
COMMENT ON COLUMN dw.fact_order.pay_status       IS '支付状态（已支付/已退款）';
COMMENT ON COLUMN dw.fact_order.gmv_amount       IS '订单成交金额（元，不含运费，不扣退款）';

CREATE TABLE dw.fact_order_item (
    order_id      bigint        NOT NULL REFERENCES dw.fact_order (order_id),
    item_id       integer       NOT NULL,
    category_id   integer       NOT NULL REFERENCES dw.dim_category (category_id),
    paid_amount   numeric(12,2) NOT NULL,
    qty           integer       NOT NULL,
    is_returned   boolean       NOT NULL,
    return_amount numeric(12,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, item_id)
);
COMMENT ON TABLE  dw.fact_order_item                IS '订单明细事实：一单内一商品一行（类目粒度）';
COMMENT ON COLUMN dw.fact_order_item.order_id       IS '订单ID（外键 fact_order）';
COMMENT ON COLUMN dw.fact_order_item.item_id        IS '行项目序号（单内递增）';
COMMENT ON COLUMN dw.fact_order_item.category_id    IS '叶子类目ID（外键 dim_category）';
COMMENT ON COLUMN dw.fact_order_item.paid_amount    IS '行成交金额（元，合计与订单 GMV 对账）';
COMMENT ON COLUMN dw.fact_order_item.qty            IS '购买件数';
COMMENT ON COLUMN dw.fact_order_item.is_returned    IS '是否退货';
COMMENT ON COLUMN dw.fact_order_item.return_amount  IS '退货金额（元，归属原订单统计周期）';

CREATE TABLE dw.fact_traffic_daily (
    date       date   NOT NULL REFERENCES dw.dim_date (date),
    channel_id text   NOT NULL REFERENCES dw.dim_channel (channel_id),
    visitors   bigint NOT NULL,
    PRIMARY KEY (date, channel_id)
);
COMMENT ON TABLE  dw.fact_traffic_daily            IS '流量事实：日×渠道一行（转化率分母）';
COMMENT ON COLUMN dw.fact_traffic_daily.date        IS '统计日期（外键 dim_date）';
COMMENT ON COLUMN dw.fact_traffic_daily.channel_id  IS '渠道编码（外键 dim_channel）';
COMMENT ON COLUMN dw.fact_traffic_daily.visitors    IS '访客数（去重 UV）';

-- ---------------------------------------------------------------------------
-- seed（数据有故事：渠道A领先可讲、美妆退货率高、日粒度有起伏、同比方向明确）
-- ---------------------------------------------------------------------------
INSERT INTO dw.dim_date
SELECT d::date,
       EXTRACT(YEAR  FROM d)::int,
       EXTRACT(MONTH FROM d)::int,
       EXTRACT(DAY   FROM d)::int,
       CASE
           WHEN d::date BETWEEN DATE '2026-06-16' AND DATE '2026-06-18' THEN '正式'
           WHEN d::date BETWEEN DATE '2026-06-01' AND DATE '2026-06-15' THEN '预热'
           WHEN d::date BETWEEN DATE '2026-06-19' AND DATE '2026-06-20' THEN '返场'
           WHEN d::date BETWEEN DATE '2025-06-16' AND DATE '2025-06-18' THEN '正式'
           WHEN d::date BETWEEN DATE '2025-06-01' AND DATE '2025-06-15' THEN '预热'
           WHEN d::date BETWEEN DATE '2025-06-19' AND DATE '2025-06-25' THEN '返场'
           ELSE '日常'
       END,
       (d::date BETWEEN DATE '2026-06-01' AND DATE '2026-06-20')
           OR (d::date BETWEEN DATE '2025-06-01' AND DATE '2025-06-25'),
       CASE
           WHEN d::date BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'
               THEN FLOOR((d::date - DATE '2026-06-16') / 7)::int
           ELSE NULL
       END
FROM generate_series(DATE '2025-06-01', DATE '2026-06-30', INTERVAL '1 day') g(d);

INSERT INTO dw.dim_channel (channel_id, channel_name, channel_type) VALUES
    ('CH_A', '渠道A', '自有商城'),
    ('CH_B', '渠道B', '平台电商'),
    ('CH_C', '渠道C', '社交电商'),
    ('CH_D', '渠道D', '线下门店');

INSERT INTO dw.dim_category (category_id, level1_id, level1_name, level2_name) VALUES
    (101, 100, '美妆个护', '彩妆'),
    (102, 100, '美妆个护', '护肤'),
    (103, 100, '美妆个护', '美妆工具'),
    (201, 200, '服饰',     '男装'),
    (202, 200, '服饰',     '女装'),
    (203, 200, '服饰',     '内衣'),
    (301, 300, '家居',     '家清'),
    (302, 300, '家居',     '家纺');

-- 订单：仅两个 618 窗口有数（2025-06-01~25 / 2026-06-01~30），渠道A 占四成领先
INSERT INTO dw.fact_order (order_id, customer_id, channel_id, order_date, is_new_customer, pay_status, gmv_amount)
WITH days AS (
    SELECT d::date AS d,
           (d::date - DATE '2025-06-01')::int AS ord,
           CASE
               WHEN d::date BETWEEN DATE '2026-06-16' AND DATE '2026-06-18' THEN 260
               WHEN d::date BETWEEN DATE '2026-06-01' AND DATE '2026-06-20' THEN 150
               WHEN d::date BETWEEN DATE '2025-06-16' AND DATE '2025-06-18' THEN 230
               WHEN d::date BETWEEN DATE '2025-06-01' AND DATE '2025-06-25' THEN 130
               ELSE 0
           END AS n
    FROM generate_series(DATE '2025-06-01', DATE '2026-06-30', INTERVAL '1 day') t(d)
), expanded AS (
    SELECT d, ord, gs.i AS i
    FROM days
    CROSS JOIN LATERAL generate_series(1, GREATEST(days.n, 1)) gs(i)
    WHERE days.n > 0
)
SELECT (e.ord * 1000 + e.i)::bigint                                   AS order_id,
       (100000 + (e.ord * 131 + e.i) % 700)::bigint                   AS customer_id,
       (ARRAY['CH_A','CH_A','CH_A','CH_A','CH_B','CH_B','CH_B','CH_C','CH_C','CH_D'])[1 + (e.ord * 7 + e.i * 3) % 10] AS channel_id,
       e.d                                                            AS order_date,
       (e.i + e.ord) % 10 < 3                                         AS is_new_customer,
       CASE WHEN (e.ord * 13 + e.i) % 10 = 0 THEN '已退款' ELSE '已支付' END AS pay_status,
       ROUND((80 + (e.i * 37) % 700
              + CASE
                    WHEN e.d BETWEEN DATE '2026-06-16' AND DATE '2026-06-18' THEN 220
                    WHEN e.d BETWEEN DATE '2025-06-16' AND DATE '2025-06-18' THEN 220
                    WHEN e.d BETWEEN DATE '2026-06-01' AND DATE '2026-06-20' THEN 80
                    WHEN e.d BETWEEN DATE '2025-06-01' AND DATE '2025-06-25' THEN 80
                    ELSE 0
                END)::numeric, 2)                                     AS gmv_amount
FROM expanded e;

-- 明细：每单 1~3 行；美妆类目退货率 ~15%，其余 ~4%；行金额合计≈订单 GMV
INSERT INTO dw.fact_order_item (order_id, item_id, category_id, paid_amount, qty, is_returned, return_amount)
SELECT base.order_id,
       base.k,
       base.cat,
       base.paid,
       base.qty,
       base.returned,
       CASE WHEN base.returned THEN base.paid ELSE 0 END
FROM (
    SELECT o.order_id,
           it.k,
           (ARRAY[101,102,103,201,202,203,301,302])[1 + (o.order_id * 5 + it.k * 11) % 8] AS cat,
           ROUND(o.gmv_amount / (1 + o.order_id % 3), 2)                             AS paid,
           1 + (o.order_id + it.k) % 2                                               AS qty,
           ((CASE WHEN (ARRAY[101,102,103,201,202,203,301,302])[1 + (o.order_id * 5 + it.k * 11) % 8] < 200
                  THEN (o.order_id * 7 + it.k) % 100
                  ELSE (o.order_id * 3 + it.k) % 100 END)
            < (CASE WHEN (ARRAY[101,102,103,201,202,203,301,302])[1 + (o.order_id * 5 + it.k * 11) % 8] < 200
                    THEN 15 ELSE 4 END))                                             AS returned
    FROM dw.fact_order o
    CROSS JOIN LATERAL generate_series(1, 1 + o.order_id % 3) it(k)
) base;

-- 流量：日×渠道；档期放量，日起伏
INSERT INTO dw.fact_traffic_daily (date, channel_id, visitors)
SELECT d::date,
       c.channel_id,
       (CASE c.channel_id
            WHEN 'CH_A' THEN 4200 WHEN 'CH_B' THEN 3100 WHEN 'CH_C' THEN 2100 ELSE 1100 END
        + (EXTRACT(DAY FROM d)::int * 137) % 900
        + CASE
              WHEN d::date BETWEEN DATE '2026-06-16' AND DATE '2026-06-18' THEN 2600
              WHEN d::date BETWEEN DATE '2025-06-16' AND DATE '2025-06-18' THEN 2600
              WHEN d::date BETWEEN DATE '2026-06-01' AND DATE '2026-06-20' THEN 900
              WHEN d::date BETWEEN DATE '2025-06-01' AND DATE '2025-06-25' THEN 900
              ELSE 0
          END)::bigint
FROM generate_series(DATE '2025-06-01', DATE '2026-06-30', INTERVAL '1 day') t(d)
CROSS JOIN dw.dim_channel c
WHERE (d::date BETWEEN DATE '2025-06-01' AND DATE '2025-06-25')
   OR (d::date BETWEEN DATE '2026-06-01' AND DATE '2026-06-30');

ANALYZE dw.dim_date;
ANALYZE dw.dim_channel;
ANALYZE dw.dim_category;
ANALYZE dw.fact_order;
ANALYZE dw.fact_order_item;
ANALYZE dw.fact_traffic_daily;

COMMIT;

-- chatbi_ro 只读兜底授权（postgres 所建表经 default privileges 已授予，这里幂等再授一次）
GRANT USAGE  ON SCHEMA dw TO chatbi_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA dw TO chatbi_ro;
