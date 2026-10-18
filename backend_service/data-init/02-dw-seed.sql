-- 电商大促复盘 · dw 种子数据（07 第 2 轮）
-- 依据：backend_service/data-init/01-dw-ddl.sql、docs/metrics-dictionary.md v0.2 §2/§3/§4/§5、docs/测例.md T01-T15
-- 形态：INSERT ... SELECT + generate_series，setseed 固定随机种子，整文件可重复执行（依赖 01 的 IF NOT EXISTS；重跑前需 TRUNCATE 六表，见文件末尾注释）
-- 口径自洽：fact_order.gmv_amount 由明细 paid_amount 合计回填；退货仅发生在已支付订单；return_amount ≤ paid_amount
-- 数据故事：渠道 A GMV 领先（A>B>C>D 不并列）；渠道 D 转化率最高；美妆相关类目退货率 > 8%；2026 vs 2025 同比约 +80%；新客约四成

BEGIN;

SELECT setseed(0.42);

-- ========== 1. dim_channel ==========
INSERT INTO dw.dim_channel (channel_id, channel_name) VALUES
    (1, '渠道A'), (2, '渠道B'), (3, '渠道C'), (4, '渠道D');

-- ========== 2. dim_category（两级；「美妆」命中 一级「美妆个护」+ 二级「美妆工具」等多候选 → T09） ==========
INSERT INTO dw.dim_category (category_id, level1_id, level1_name, level2_name) VALUES
    (101, 1, '美妆个护', '护肤'),
    (102, 1, '美妆个护', '彩妆'),
    (103, 1, '美妆个护', '美妆工具'),
    (201, 2, '服饰',     '女装'),
    (202, 2, '服饰',     '男装'),
    (203, 2, '服饰',     '鞋靴'),
    (301, 3, '家电',     '大家电'),
    (302, 3, '家电',     '厨房小电'),
    (401, 4, '食品',     '休闲零食'),
    (402, 4, '食品',     '酒水饮料');

-- ========== 3. dim_date（2025-06-01 ~ 2026-06-30；档期口径按 metrics-dictionary §4.1） ==========
INSERT INTO dw.dim_date (date, year, month, day, promo_phase, is_promo, promo_relative_week)
SELECT
    d::date,
    extract(year  FROM d)::smallint,
    extract(month FROM d)::smallint,
    extract(day   FROM d)::smallint,
    CASE
        WHEN to_char(d, 'MM-DD') BETWEEN '06-01' AND '06-15' THEN '预热'
        WHEN to_char(d, 'MM-DD') BETWEEN '06-16' AND '06-18' THEN '正式'
        WHEN to_char(d, 'MM-DD') BETWEEN '06-19' AND '06-20' THEN '返场'
        ELSE '日常'
    END,
    (to_char(d, 'MM-DD') BETWEEN '06-01' AND '06-20'),
    CASE
        WHEN to_char(d, 'MM-DD') BETWEEN '06-09' AND '06-15' THEN '前一周'
        WHEN to_char(d, 'MM-DD') BETWEEN '06-16' AND '06-18' THEN '大促周'
        WHEN to_char(d, 'MM-DD') BETWEEN '06-19' AND '06-25' THEN '后一周'
        ELSE NULL
    END
FROM generate_series('2025-06-01'::date, '2026-06-30'::date, interval '1 day') AS d;

-- ========== 4. fact_order（约 6500 单：2026 约 4190 + 2025 约 2310，同比约 +80%） ==========
-- 日单量（2026）：预热 130/日、正式 500/日、返场 170/日、日常 80/日；2025 按 0.55 缩
-- 渠道权重 A42% B26% C18% D14%；支付率约 92%；客户池 3000（首单=新客）
WITH win AS (
    SELECT d.date, extract(year FROM d.date)::int AS yr, d.promo_phase
    FROM dw.dim_date d
    WHERE d.date BETWEEN '2025-06-01' AND '2025-06-25'
       OR d.date BETWEEN '2026-06-01' AND '2026-06-25'
),
cnt AS (
    SELECT date, yr,
           round((CASE promo_phase WHEN '预热' THEN 130 WHEN '正式' THEN 500 WHEN '返场' THEN 170 ELSE 80 END)
                 * (CASE WHEN yr = 2025 THEN 0.55 ELSE 1.0 END))::int AS n
    FROM win
),
orders AS (
    SELECT c.date, c.yr
    FROM cnt c, generate_series(1, c.n) AS gs
),
raw AS (
    SELECT date, random() AS rc, random() AS rs, random() AS rcust
    FROM orders
),
mapped AS (
    SELECT date,
           CASE WHEN rc < 0.42 THEN 1 WHEN rc < 0.68 THEN 2 WHEN rc < 0.86 THEN 3 ELSE 4 END AS channel_id,
           CASE WHEN rs < 0.92 THEN '已支付' ELSE '已取消' END AS pay_status,
           (floor(rcust * 3000) + 1)::bigint AS customer_id
    FROM raw
),
numbered AS (
    SELECT row_number() OVER (ORDER BY date, random()) AS order_id, *
    FROM mapped
),
flagged AS (
    SELECT *, row_number() OVER (PARTITION BY customer_id ORDER BY date, order_id) AS rn
    FROM numbered
)
INSERT INTO dw.fact_order (order_id, customer_id, channel_id, order_date, is_new_customer, pay_status, gmv_amount)
SELECT order_id, customer_id, channel_id, date, (rn = 1), pay_status, 0
FROM flagged;

-- ========== 5. fact_order_item（每单 1~3 行；类目加权；退货概率按类目差异化） ==========
WITH base AS (
    SELECT o.order_id,
           o.pay_status,
           g.item_id,
           (ARRAY[101,101,102,102,103,201,201,202,203,301,302,401,402])[1 + floor(random() * 13)]::smallint AS category_id,
           (1 + floor(random() * 3))::smallint AS qty,
           round(((60 + random() * 600) * (1 + floor(random() * 3)))::numeric, 2) AS paid_amount
    FROM (
        SELECT order_id, pay_status, (1 + floor(random() * 3))::int AS n_items
        FROM dw.fact_order
    ) o
    JOIN LATERAL generate_series(1, o.n_items) AS g(item_id) ON true
),
ret AS (
    SELECT *,
           (pay_status = '已支付' AND random() < CASE category_id
                WHEN 101 THEN 0.15  -- 护肤
                WHEN 102 THEN 0.14  -- 彩妆
                WHEN 103 THEN 0.06  -- 美妆工具
                WHEN 201 THEN 0.12  -- 女装
                WHEN 202 THEN 0.08  -- 男装
                WHEN 203 THEN 0.09  -- 鞋靴
                WHEN 301 THEN 0.03  -- 大家电
                WHEN 302 THEN 0.04  -- 厨房小电
                ELSE 0.02           -- 食品
           END) AS is_returned
    FROM base
)
INSERT INTO dw.fact_order_item (order_id, item_id, category_id, paid_amount, qty, is_returned, return_amount)
SELECT order_id, item_id, category_id, paid_amount, qty, is_returned,
       CASE WHEN is_returned THEN round((paid_amount * (0.6 + random() * 0.4))::numeric, 2) ELSE 0 END
FROM ret;

-- 订单主表 GMV 由明细合计回填，保证「明细合计对得上主表」
UPDATE dw.fact_order fo
SET gmv_amount = t.s
FROM (SELECT order_id, sum(paid_amount) AS s FROM dw.fact_order_item GROUP BY order_id) t
WHERE fo.order_id = t.order_id;

-- ========== 6. fact_traffic_daily（日×渠道 UV；转化率分母，量级保证转化率 2%~6%） ==========
-- 渠道 UV 基数：A1600 B1050 C700 D420；档期系数 预热×1.3 正式×3.0 返场×1.6 日常×0.8；2025×0.55
INSERT INTO dw.fact_traffic_daily (date, channel_id, visitors)
SELECT d.date,
       ch.channel_id,
       round((CASE ch.channel_id WHEN 1 THEN 1600 WHEN 2 THEN 1050 WHEN 3 THEN 700 ELSE 420 END)
             * (CASE d.promo_phase WHEN '预热' THEN 1.3 WHEN '正式' THEN 3.0 WHEN '返场' THEN 1.6 ELSE 0.8 END)
             * (CASE WHEN extract(year FROM d.date) = 2025 THEN 0.55 ELSE 1.0 END)
             * (0.9 + random() * 0.2))::int
FROM dw.dim_date d
CROSS JOIN dw.dim_channel ch
WHERE d.date BETWEEN '2025-06-01' AND '2025-06-25'
   OR d.date BETWEEN '2026-06-01' AND '2026-06-25';

COMMIT;

-- 重跑方式（整文件幂等重来一次）：
--   TRUNCATE dw.fact_order_item, dw.fact_order, dw.fact_traffic_daily, dw.dim_channel, dw.dim_category, dw.dim_date CASCADE;
--   再执行本文件。
