import type { AnswerEvent } from '../../api/types';

/** 通用信封基底 */
function envelope(question: string, overrides: Partial<AnswerEvent> = {}): Pick<AnswerEvent, 'turn_id' | 'session_id' | 'question'> {
  return { turn_id: 'turn-0001', session_id: 'session-0001', question, ...overrides };
}

const caliberGmvChannel = {
  summary: 'GMV ｜ 按渠道 ｜ 2026-06-01 至 2026-06-20 ｜ 无额外筛选',
  detail: {
    metrics: ['GMV'],
    dimensions: ['渠道'],
    time_range: '2026-06-01 至 2026-06-20（618 大促期）',
    filters: [],
    comparison: null as string | null,
  },
};

/** AC-8/F14：非空 answer（bar） */
export const answerBar: AnswerEvent = {
  ...envelope('618 大促期间各渠道 GMV，按从高到低排'),
  table: {
    columns: [
      { field: 'channel', label: '渠道', format: 'text' },
      { field: 'gmv', label: 'GMV（元）', format: 'money' },
    ],
    rows: [
      { channel: '渠道 A', gmv: 120345678.9 },
      { channel: '渠道 B', gmv: 98765432.1 },
      { channel: '渠道 C', gmv: 76543210 },
    ],
    truncated: false,
    display_limit: 500,
  },
  chart: {
    type: 'bar',
    x_field: 'channel',
    series: [{ field: 'gmv', label: 'GMV（元）' }],
    switchable: ['bar', 'line', 'pie'],
  },
  insight: '渠道 A 的 GMV 最高，为 1.2 亿，占全渠道约 42%。',
  caliber: caliberGmvChannel,
  comparison: null,
  data_time_range: { start: '2026-06-01', end: '2026-06-20', label: '618 大促期' },
  queried_at: '2026-10-17T10:00:00Z',
  saveable: true,
};

/** F15：空结果 answer（rows=[]、chart=null、saveable=false、无图无表无保存） */
export const answerEmpty: AnswerEvent = {
  ...envelope('上周海外渠道的 GMV'),
  table: {
    columns: [
      { field: 'channel', label: '渠道', format: 'text' },
      { field: 'gmv', label: 'GMV（元）', format: 'money' },
    ],
    rows: [],
    truncated: false,
    display_limit: 500,
  },
  chart: null,
  insight: '该时间范围内没有查到符合口径的数据。',
  caliber: {
    summary: 'GMV ｜ 按渠道 ｜ 2026-10-05 至 2026-10-11 ｜ 渠道=海外',
    detail: {
      metrics: ['GMV'],
      dimensions: ['渠道'],
      time_range: '2026-10-05 至 2026-10-11',
      filters: ['渠道=海外'],
      comparison: null,
    },
  },
  comparison: null,
  data_time_range: { start: '2026-10-05', end: '2026-10-11', label: '' },
  queried_at: '2026-10-17T10:05:00Z',
  saveable: false,
};

/** 图型样例：line / trend_line / grouped_bar / pie（AC-9 mapper 五型） */
export const answerLine: AnswerEvent = {
  ...envelope('最近 7 天每日 GMV 趋势'),
  table: {
    columns: [
      { field: 'dt', label: '日期', format: 'text' },
      { field: 'gmv', label: 'GMV（元）', format: 'money' },
    ],
    rows: [
      { dt: '10-11', gmv: 8100000 },
      { dt: '10-12', gmv: 9200000 },
      { dt: '10-13', gmv: 8800000 },
    ],
    truncated: false,
    display_limit: 500,
  },
  chart: {
    type: 'line',
    x_field: 'dt',
    series: [{ field: 'gmv', label: 'GMV（元）' }],
    switchable: ['line', 'bar'],
  },
  insight: '近 7 天 GMV 在 810 万至 920 万间波动。',
  caliber: caliberGmvChannel,
  comparison: null,
  data_time_range: { start: '2026-10-11', end: '2026-10-17', label: '' },
  queried_at: '2026-10-17T10:10:00Z',
  saveable: true,
};

/** 对比 answer：truncated=true、rate_delta=null（不可比）（AC-13/F19） */
export const answerComparison: AnswerEvent = {
  ...envelope('618 大促各渠道 GMV 同比', { turn_id: 'turn-0002' }),
  table: {
    columns: [
      { field: 'channel', label: '渠道', format: 'text' },
      { field: 'gmv_current', label: '本期 GMV（元）', format: 'money' },
      { field: 'gmv_prior', label: '去年同期 GMV（元）', format: 'money' },
      { field: 'value_delta', label: '变化值（元）', format: 'money' },
      { field: 'rate_delta', label: '变化率', format: 'percent' },
    ],
    rows: [
      { channel: '渠道 A', gmv_current: 120345678.9, gmv_prior: 101643200, value_delta: '18702478.90', rate_delta: '18.3' },
      { channel: '渠道 B', gmv_current: 98765432.1, gmv_prior: 88123456, value_delta: '10641976.10', rate_delta: '12.1' },
      { channel: '渠道 C', gmv_current: 76543210, gmv_prior: 0, value_delta: '76543210.00', rate_delta: null },
    ],
    truncated: true,
    display_limit: 2,
  },
  chart: {
    type: 'trend_line',
    x_field: 'channel',
    series: [
      { field: 'gmv_current', label: '本期 GMV（元）' },
      { field: 'gmv_prior', label: '去年同期 GMV（元）' },
    ],
    switchable: ['trend_line', 'grouped_bar'],
  },
  insight: '渠道 A 的 GMV 同比增长 18.3%。',
  caliber: {
    summary: 'GMV ｜ 按渠道 ｜ 618 大促期 ｜ 对比去年同期',
    detail: {
      metrics: ['GMV'],
      dimensions: ['渠道'],
      time_range: '2026-06-01 至 2026-06-20（618 大促期）',
      filters: [],
      comparison: '同比去年同期',
    },
  },
  comparison: {
    mode: 'yoy',
    periods: ['本期', '去年同期'],
    changes: [
      { key: '渠道 A', value_delta: '18702478.90', rate_delta: '18.3' },
      { key: '渠道 B', value_delta: '10641976.10', rate_delta: '12.1' },
      { key: '渠道 C', value_delta: '76543210.00', rate_delta: null },
    ],
  },
  data_time_range: { start: '2026-06-01', end: '2026-06-20', label: '618 大促期' },
  queried_at: '2026-10-17T10:15:00Z',
  saveable: true,
};

/** grouped_bar 样例（同表） */
export const answerGroupedBar: AnswerEvent = {
  ...answerComparison,
  turn_id: 'turn-0003',
  chart: {
    type: 'grouped_bar',
    x_field: 'channel',
    series: [
      { field: 'gmv_current', label: '本期 GMV（元）' },
      { field: 'gmv_prior', label: '去年同期 GMV（元）' },
    ],
    switchable: ['grouped_bar', 'trend_line'],
  },
};

/** pie 样例 */
export const answerPie: AnswerEvent = {
  ...answerBar,
  turn_id: 'turn-0004',
  chart: {
    type: 'pie',
    x_field: 'channel',
    series: [{ field: 'gmv', label: 'GMV（元）' }],
    switchable: ['pie', 'bar'],
  },
};
