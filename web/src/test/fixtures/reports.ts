import type {
  HealthResponse,
  ReportDetail,
  ReportListItem,
  RefreshResponse,
  SaveReportResponse,
} from '../../api/types';
import { answerBar, answerEmpty } from './answers';

export const reportListItems: ReportListItem[] = [
  {
    id: 'report-0002',
    title: '618 各渠道 GMV 同比',
    caliber_summary: 'GMV ｜ 按渠道 ｜ 618 大促期 ｜ 对比去年同期',
    queried_at: '2026-10-17T10:15:00Z',
    data_time_range: { start: '2026-06-01', end: '2026-06-20', label: '618 大促期' },
    created_at: '2026-10-17T10:20:00Z',
  },
  {
    id: 'report-0001',
    title: '618 各渠道 GMV 排行',
    caliber_summary: 'GMV ｜ 按渠道 ｜ 2026-06-01 至 2026-06-20 ｜ 无额外筛选',
    queried_at: '2026-10-17T10:00:00Z',
    data_time_range: { start: '2026-06-01', end: '2026-06-20', label: '618 大促期' },
    created_at: '2026-10-17T10:05:00Z',
  },
];

/** 详情：直渲 snapshot（含图） */
export const reportDetail: ReportDetail = {
  id: 'report-0001',
  title: '618 各渠道 GMV 排行',
  question: '618 大促期间各渠道 GMV，按从高到低排',
  caliber: answerBar.caliber,
  snapshot: {
    insight: answerBar.insight,
    chart: answerBar.chart,
    table: answerBar.table,
    comparison: null,
  },
  data_time_range: answerBar.data_time_range,
  queried_at: '2026-10-17T10:00:00Z',
  created_at: '2026-10-17T10:05:00Z',
  updated_at: '2026-10-17T10:05:00Z',
};

/** 详情：chart=null（无图区） */
export const reportDetailNoChart: ReportDetail = {
  ...reportDetail,
  id: 'report-0003',
  title: '618 大促总 GMV',
  snapshot: {
    insight: '618 大促总 GMV 为 2.96 亿。',
    chart: null,
    table: {
      columns: [{ field: 'gmv', label: 'GMV（元）', format: 'money' }],
      rows: [{ gmv: 295654321 }],
      truncated: false,
      display_limit: 500,
    },
    comparison: null,
  },
};

export const saveReportOk: SaveReportResponse = {
  id: 'report-0004',
  title: '618 各渠道 GMV 排行',
  created_at: '2026-10-17T11:00:00Z',
};

// ---- 刷新四态（AC-17/F28） ----
export const refreshAnswer: RefreshResponse = {
  action: 'answer',
  question: reportDetail.question,
  table: answerBar.table,
  chart: answerBar.chart,
  insight: '刷新后渠道 A 的 GMV 最高，为 1.3 亿。',
  caliber: answerBar.caliber,
  comparison: null,
  data_time_range: answerBar.data_time_range,
  queried_at: '2026-10-17T12:00:00Z',
  saveable: true,
};

export const refreshEmptyAnswer: RefreshResponse = {
  action: 'answer',
  question: reportDetail.question,
  table: answerEmpty.table,
  chart: null,
  insight: answerEmpty.insight,
  caliber: answerEmpty.caliber,
  comparison: null,
  data_time_range: answerEmpty.data_time_range,
  queried_at: '2026-10-17T12:00:00Z',
  saveable: false,
};

export const refreshQueryTimeout: RefreshResponse = {
  action: 'query_failed',
  reason_code: 'QUERY_TIMEOUT',
  reason_text: '取数超时了，数据查询时间过长。',
  suggestions: [],
};

export const refreshQueryGenFailed: RefreshResponse = {
  action: 'query_gen_failed',
  reason_code: 'GEN_LINT_EXHAUSTED',
  reason_text: '这个问法比较复杂，多次尝试后仍无法生成可靠的查询，请换个问法。',
  suggestions: [
    { label: '618 各渠道 GMV 排行', question: '618 大促期间各渠道 GMV 是多少，按从高到低排' },
  ],
};

export const refreshNotAnswerable: RefreshResponse = {
  action: 'not_answerable',
  reason_code: 'NO_MATCHING_DATA',
  reason_text: '平台目前没有该指标的数据。',
  suggestions: [],
};

export const healthOk: HealthResponse = { status: 'ok', checks: { db: 'ok', llm: 'ok', embedding: 'unconfigured' } };
export const healthDegraded: HealthResponse = { status: 'degraded', checks: { db: 'ok', llm: 'error', embedding: 'unconfigured' } };
