/**
 * ChainResult 的 TS 镜像（单一来源手写对齐）。
 *
 * 权威：docs/SDD-算法应用.md §6 ChainResult（字段语义）、docs/SDD-后端.md §3（信封与报文）。
 * 与 algorithm/state.py 的 pydantic 模型逐字段对齐：
 * - value_delta/rate_delta 为字符串（Decimal 序列化，金额 2 位/率 1 位）；
 * - caliber.detail.metrics/dimensions/filters 为 string[]，time_range 为 string；
 * - chart 可为 null（单标量/空结果不画图）。
 * 全仓禁用旧术语（原解读字段/旧图型名，guard 测试留证）。
 */

// ---- 五图型（chart 可 null） ----
export const CHART_TYPES = ['bar', 'line', 'trend_line', 'grouped_bar', 'pie'] as const;
export type ChartType = (typeof CHART_TYPES)[number];

// ---- SSE stage 三值 ----
export const STAGES = ['understanding', 'checking_caliber', 'querying'] as const;
export type Stage = (typeof STAGES)[number];

// ---- 终态（前端消费形态） ----
export const TERMINAL_EVENTS = [
  'answer',
  'clarification',
  'rejection',
  'error',
  'cancelled',
] as const;
export type TerminalEvent = (typeof TERMINAL_EVENTS)[number];

// ---- answer 载荷 ----
export interface TableColumn {
  field: string;
  label: string;
  /** money | percent | number | number:2 | text（算法 TableData.format） */
  format: string;
}

export interface TableData {
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  truncated: boolean;
  display_limit: number;
}

export interface ChartSeries {
  field: string;
  label: string;
}

export interface ChartSpec {
  type: ChartType;
  x_field: string;
  series: ChartSeries[];
  /** 允许前端本地切换的图型 */
  switchable: ChartType[];
}

export interface CaliberDetail {
  metrics: string[];
  dimensions: string[];
  /** 一段时间文本（如「618 大促期」或「2026-06-01~2026-06-20」） */
  time_range: string;
  filters: string[];
  comparison: string | null;
}

export interface Caliber {
  summary: string;
  detail: CaliberDetail;
}

/** value_delta/rate_delta 为 Decimal 字符串；rate_delta=null＝分母为 0「不可比」 */
export interface ComparisonChange {
  key: string;
  value_delta: string;
  rate_delta: string | null;
}

export interface ComparisonResult {
  mode: string;
  periods: string[];
  changes: ComparisonChange[];
}

/** 后端信封：AnswerEvent（五业务字段逐字镜像 + 信封字段） */
export interface AnswerEvent {
  turn_id: string;
  session_id: string;
  question: string;
  table: TableData;
  chart: ChartSpec | null;
  insight: string;
  caliber: Caliber;
  comparison: ComparisonResult | null;
  /** 后端从 QuerySpec.time_range 派生；可能为 null */
  data_time_range: { start: string; end: string; label: string } | null;
  queried_at: string;
  /** 后端派生：= answer 且 table.rows 非空 */
  saveable: boolean;
}

// ---- 澄清载荷（ClarificationPayload = 算法 clarify + status） ----
export const CLARIFY_REASON_CODES = [
  'METRIC_DIM_AMBIGUOUS',
  'MISSING_TIME',
  'VAGUE',
  'ANAPHORA_UNRESOLVED',
] as const;
export type ClarifyReasonCode = (typeof CLARIFY_REASON_CODES)[number];

export const CLARIFY_INPUT_TYPES = [
  'single_choice',
  'time_quick',
  'question_suggestions',
] as const;
export type ClarifyInputType = (typeof CLARIFY_INPUT_TYPES)[number];

export interface ClarifyOption {
  value: string;
  label: string;
}

export interface ClarifySuggestion {
  question: string;
}

export interface ClarifyPayload {
  clarify_id: string;
  /** 两轮上限：1 | 2 */
  round: number;
  title: string;
  reason_code: ClarifyReasonCode;
  input_type: ClarifyInputType;
  options: ClarifyOption[];
  /** input_type=question_suggestions 时 2~4 个 */
  suggestions: ClarifySuggestion[];
  allow_custom_text: boolean;
  /** 落库态：pending | confirmed | cancelled（SSE 帧/消息还原共用） */
  status: 'pending' | 'confirmed' | 'cancelled';
}

// ---- 拒答载荷（六 reason_code，三类 action 同构） ----
export const REJECTION_REASON_CODES = [
  'NOT_DATA_QUESTION',
  'NO_MATCHING_DATA',
  'CALIBER_CONFLICT',
  'GEN_LINT_EXHAUSTED',
  'QUERY_TIMEOUT',
  'QUERY_ERROR',
] as const;
export type RejectionReasonCode = (typeof REJECTION_REASON_CODES)[number];

export interface RejectionSuggestion {
  label: string;
  question: string;
}

export interface RejectionPayload {
  reason_code: RejectionReasonCode;
  /** 大白话业务文案，前端不另写 */
  reason_text: string;
  suggestions: RejectionSuggestion[];
}

/** 业务拒答四码（无重试样式）；QUERY_TIMEOUT/QUERY_ERROR 为故障态＋重试 */
export const BUSINESS_REJECTION_CODES: readonly RejectionReasonCode[] = [
  'NOT_DATA_QUESTION',
  'NO_MATCHING_DATA',
  'CALIBER_CONFLICT',
  'GEN_LINT_EXHAUSTED',
];
export const RETRYABLE_REJECTION_CODES: readonly RejectionReasonCode[] = [
  'QUERY_TIMEOUT',
  'QUERY_ERROR',
];

// ---- error 载荷 ----
export interface ErrorPayload {
  code: string;
  message: string;
  retryable: boolean;
}

// ---- 消息还原（GET /sessions/{id}/messages） ----
export const MESSAGE_TYPES = ['user', 'clarification', 'answer', 'rejection', 'note'] as const;
export type MessageType = (typeof MESSAGE_TYPES)[number];

export interface Message {
  id: string;
  seq: number;
  type: MessageType;
  created_at: string;
  payload: MessagePayload;
}

/** 消息/流终态载荷（error 与 cancelled 仅出现在 SSE 流，不落库还原） */
export type MessagePayload =
  | { question: string } // user
  | ClarifyPayload // clarification（含最终 status）
  | AnswerEvent // answer 终态切片
  | RejectionPayload // rejection
  | ErrorPayload // error 终态（流内）
  | { turn_id: string } // cancelled 终态（流内）
  | { kind: 'cancelled' | 'system'; text: string }; // note

export interface SessionSummary {
  id: string;
  title: string;
  message_count: number;
  last_question_at: string;
  created_at: string;
}

export interface SessionMessagesResponse {
  session: SessionSummary;
  messages: Message[];
}

// ---- HTTP 层 ----
export interface TurnStartResponse {
  turn_id: string;
  session_id: string;
  status: 'running';
}

export interface CancelResponse {
  turn_id: string;
  status: 'cancelling';
}

/** 后端错误信封（§3.1） */
export interface HttpErrorEnvelope {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    /** E_NAME_CONFLICT 附带同名报表信息 */
    existing?: { id: string; title: string };
  };
}

/** 错误码联合（§8；保留类型化分支用） */
export const ERROR_CODES = [
  'E_VALIDATION',
  'E_CLARIFY_EXPIRED',
  'E_NAME_CONFLICT',
  'E_REPORT_NOT_SAVEABLE',
  'E_TURN_NOT_FOUND',
  'E_NOT_FOUND',
  'E_LLM_UNAVAILABLE',
  'E_INTERNAL',
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

// ---- 报表 ----
export interface ReportListItem {
  id: string;
  title: string;
  caliber_summary: string;
  queried_at: string;
  data_time_range: { start: string; end: string; label: string } | null;
  created_at: string;
}

export interface ReportDetail {
  id: string;
  title: string;
  question: string;
  caliber: Caliber;
  snapshot: {
    insight: string;
    chart: ChartSpec | null;
    table: TableData;
    comparison: ComparisonResult | null;
  };
  data_time_range: { start: string; end: string; label: string } | null;
  queried_at: string;
  created_at: string;
  updated_at: string;
}

export interface SaveReportResponse {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
}

/** 刷新：同步返回终态同构体 */
export type RefreshResponse =
  | ({ action: 'answer' } & Omit<AnswerEvent, 'turn_id' | 'session_id'>)
  | ({ action: 'query_gen_failed' | 'query_failed' | 'not_answerable' } & RejectionPayload)
  | ({ action: 'error' } & ErrorPayload);

export interface ContinueSessionResponse {
  session_id: string;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  checks: { db: string; llm: string; embedding: string };
}

// ---- 请求体 ----
/** POST /chat/turns 三态互斥：question | clarify | recalibrate */
export interface StartTurnRequest {
  session_id?: string;
  question?: string;
  clarify?: {
    clarify_id: string;
    selection: {
      /** option（单选）| time_preset（预设 key 或 {start,end}）| custom（新问题文本） */
      type: 'option' | 'time_preset' | 'custom';
      value: string | { start: string; end: string };
    };
  };
  recalibrate?: { source_turn_id: string };
}

export interface SaveReportRequest {
  turn_id: string;
  title: string;
  overwrite?: boolean;
}
