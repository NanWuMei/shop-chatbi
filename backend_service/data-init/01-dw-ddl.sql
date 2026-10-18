-- 电商大促复盘 · dw 业务表 DDL（L0 核心，3 维 + 3 事实）
-- 依据：docs/metrics-dictionary.md v0.2 §5（数仓表集大纲）、§2（指标口径）、§3（维度）、§4（档期日历）
-- 说明：
--   1. 仅 CREATE TABLE + COMMENT；dw schema 与角色由 backend_service/db/01-init.sql（compose）或 07 第 3 轮初始化 SQL 负责，本文件不重建；
--   2. 每张表、每个业务列必须中文 COMMENT——无 L1 字典时 Aligner/Coder 全靠列名+注释+枚举采样；
--   3. 枚举值用业务可读中文（渠道A/B/C/D、预热/正式/返场/日常、已支付/已取消 等），支撑 L0 枚举采样；
--   4. 种子数据不在本文件（07 第 2 轮产出）。

-- ========== 维表 ==========

CREATE TABLE IF NOT EXISTS dw.dim_date (
    date                date        PRIMARY KEY,
    year                smallint    NOT NULL,
    month               smallint    NOT NULL,
    day                 smallint    NOT NULL,
    promo_phase         varchar(8)  NOT NULL DEFAULT '日常',
    is_promo            boolean     NOT NULL DEFAULT false,
    promo_relative_week varchar(16) NULL
);
COMMENT ON TABLE  dw.dim_date                    IS '日期维表（日粒度），时间归一与档期切分的唯一依据';
COMMENT ON COLUMN dw.dim_date.date               IS '日期（主键）';
COMMENT ON COLUMN dw.dim_date.year               IS '年，如 2026';
COMMENT ON COLUMN dw.dim_date.month              IS '月，1~12';
COMMENT ON COLUMN dw.dim_date.day                IS '日，1~31';
COMMENT ON COLUMN dw.dim_date.promo_phase        IS '618大促档期：预热 / 正式 / 返场 / 日常（预热=当年6/1~6/15，正式=6/16~6/18，返场=6/19~6/20，其余=日常）';
COMMENT ON COLUMN dw.dim_date.is_promo           IS '是否大促期间（预热+正式+返场，即当年6/1~6/20）';
COMMENT ON COLUMN dw.dim_date.promo_relative_week IS '大促相对周标记：前一周(6/9~6/15) / 大促周(6/16~6/18) / 后一周(6/19~6/25)，其余为空';

CREATE TABLE IF NOT EXISTS dw.dim_channel (
    channel_id   smallint    PRIMARY KEY,
    channel_name varchar(16) NOT NULL UNIQUE
);
COMMENT ON TABLE  dw.dim_channel              IS '渠道维表';
COMMENT ON COLUMN dw.dim_channel.channel_id   IS '渠道ID（主键）';
COMMENT ON COLUMN dw.dim_channel.channel_name IS '渠道名称：渠道A / 渠道B / 渠道C / 渠道D';

CREATE TABLE IF NOT EXISTS dw.dim_category (
    category_id smallint    PRIMARY KEY,
    level1_id   smallint    NOT NULL,
    level1_name varchar(16) NOT NULL,
    level2_name varchar(16) NOT NULL
);
COMMENT ON TABLE  dw.dim_category              IS '类目维表（两级，事实表挂叶子类目）；「美妆」一词同时命中一级类目「美妆个护」与二级类目「美妆工具」等多个候选，是口径澄清的数据基础';
COMMENT ON COLUMN dw.dim_category.category_id  IS '叶子类目ID（主键）';
COMMENT ON COLUMN dw.dim_category.level1_id    IS '一级类目ID';
COMMENT ON COLUMN dw.dim_category.level1_name  IS '一级类目名称，如 美妆个护 / 服饰 / 家电 / 食品';
COMMENT ON COLUMN dw.dim_category.level2_name  IS '二级类目（叶子）名称，如 护肤 / 彩妆 / 美妆工具';

-- ========== 事实表 ==========

CREATE TABLE IF NOT EXISTS dw.fact_order (
    order_id         bigint        PRIMARY KEY,
    customer_id      bigint        NOT NULL,
    channel_id       smallint      NOT NULL REFERENCES dw.dim_channel(channel_id),
    order_date       date          NOT NULL REFERENCES dw.dim_date(date),
    is_new_customer  boolean       NOT NULL,
    pay_status       varchar(8)    NOT NULL,
    gmv_amount       numeric(12,2) NOT NULL DEFAULT 0
);
COMMENT ON TABLE  dw.fact_order                IS '订单事实表（一单一行）；GMV、AOV、转化率分子、新老客分析的主表';
COMMENT ON COLUMN dw.fact_order.order_id       IS '订单ID（主键）';
COMMENT ON COLUMN dw.fact_order.customer_id    IS '客户ID';
COMMENT ON COLUMN dw.fact_order.channel_id     IS '下单渠道（外键→dim_channel）';
COMMENT ON COLUMN dw.fact_order.order_date     IS '下单日期（外键→dim_date）';
COMMENT ON COLUMN dw.fact_order.is_new_customer IS '是否新客：true=新客（该客户首单），false=老客';
COMMENT ON COLUMN dw.fact_order.pay_status     IS '支付状态：已支付 / 已取消；GMV、转化率分子只统计「已支付」';
COMMENT ON COLUMN dw.fact_order.gmv_amount     IS '订单成交金额（元，不含运费，不扣退款退货；退货由退货率单独刻画）';

CREATE TABLE IF NOT EXISTS dw.fact_order_item (
    order_id      bigint        NOT NULL REFERENCES dw.fact_order(order_id),
    item_id       smallint      NOT NULL,
    category_id   smallint      NOT NULL REFERENCES dw.dim_category(category_id),
    paid_amount   numeric(12,2) NOT NULL DEFAULT 0,
    qty           smallint      NOT NULL DEFAULT 1,
    is_returned   boolean       NOT NULL DEFAULT false,
    return_amount numeric(12,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, item_id)
);
COMMENT ON TABLE  dw.fact_order_item               IS '订单明细事实表（一单内一商品行）；类目粒度 GMV 与退货率的来源表';
COMMENT ON COLUMN dw.fact_order_item.order_id      IS '订单ID（外键→fact_order）';
COMMENT ON COLUMN dw.fact_order_item.item_id       IS '订单内行号';
COMMENT ON COLUMN dw.fact_order_item.category_id   IS '叶子类目（外键→dim_category）';
COMMENT ON COLUMN dw.fact_order_item.paid_amount   IS '本行成交金额（元；明细合计与订单 gmv_amount 可对账）';
COMMENT ON COLUMN dw.fact_order_item.qty           IS '购买件数';
COMMENT ON COLUMN dw.fact_order_item.is_returned   IS '是否发生退货';
COMMENT ON COLUMN dw.fact_order_item.return_amount IS '退货金额（元；退货率=退货金额合计÷GMV×100%）';

CREATE TABLE IF NOT EXISTS dw.fact_traffic_daily (
    date       date     NOT NULL REFERENCES dw.dim_date(date),
    channel_id smallint NOT NULL REFERENCES dw.dim_channel(channel_id),
    visitors   integer  NOT NULL DEFAULT 0,
    PRIMARY KEY (date, channel_id)
);
COMMENT ON TABLE  dw.fact_traffic_daily            IS '流量事实表（日×渠道）；转化率的分母来源，本版无类目粒度流量';
COMMENT ON COLUMN dw.fact_traffic_daily.date       IS '日期（外键→dim_date）';
COMMENT ON COLUMN dw.fact_traffic_daily.channel_id IS '渠道（外键→dim_channel）';
COMMENT ON COLUMN dw.fact_traffic_daily.visitors   IS '访客数（UV，去重）；支付转化率=支付买家数÷访客数×100%';

-- ========== 建议索引（时间、渠道、类目、门店/维度高频过滤列） ==========
CREATE INDEX IF NOT EXISTS idx_fact_order_date      ON dw.fact_order (order_date);
CREATE INDEX IF NOT EXISTS idx_fact_order_channel   ON dw.fact_order (channel_id);
CREATE INDEX IF NOT EXISTS idx_fact_order_customer  ON dw.fact_order (customer_id);
CREATE INDEX IF NOT EXISTS idx_fact_item_category   ON dw.fact_order_item (category_id);
CREATE INDEX IF NOT EXISTS idx_fact_traffic_channel ON dw.fact_traffic_daily (channel_id);
