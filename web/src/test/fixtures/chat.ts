import type {
  ClarifyPayload,
  ErrorPayload,
  HttpErrorEnvelope,
  RejectionPayload,
  TerminalEvent,
} from '../../api/types';

/** SSE 帧（脚本化用）：event 名 + data JSON + 可选 id（Last-Event-ID） */
export interface SseFrame {
  event: 'stage' | TerminalEvent | 'done';
  data: unknown;
  id?: string;
}

// ---- 澄清：四 reason_code × 三 input_type（AC-10/F20） ----
export const clarifySingleChoice: ClarifyPayload = {
  clarify_id: 'clarify-0001',
  round: 1,
  title: '请确认类目口径',
  reason_code: 'METRIC_DIM_AMBIGUOUS',
  input_type: 'single_choice',
  options: [
    { value: 'beauty_personal_care', label: '美妆个护（一级类目）' },
    { value: 'beauty_device', label: '美容仪器（二级类目）' },
  ],
  suggestions: [],
  allow_custom_text: true,
  status: 'pending',
};

export const clarifyTimeQuick: ClarifyPayload = {
  clarify_id: 'clarify-0002',
  round: 1,
  title: '请确认时间范围',
  reason_code: 'MISSING_TIME',
  input_type: 'time_quick',
  options: [
    { value: 'current_promo', label: '本期大促' },
    { value: 'last_7_days', label: '最近 7 天' },
  ],
  suggestions: [],
  allow_custom_text: true,
  status: 'pending',
};

export const clarifyQuestionSuggestions: ClarifyPayload = {
  clarify_id: 'clarify-0003',
  round: 2,
  title: '换个问法试试',
  reason_code: 'VAGUE',
  input_type: 'question_suggestions',
  options: [],
  suggestions: [
    { question: '618 大促期间各渠道 GMV 是多少，按从高到低排' },
    { question: '618 大促期间各渠道订单量是多少' },
  ],
  allow_custom_text: true,
  status: 'pending',
};

export const clarifyAnaphora: ClarifyPayload = {
  clarify_id: 'clarify-0004',
  round: 2,
  title: '请确认"它"指的是哪个渠道',
  reason_code: 'ANAPHORA_UNRESOLVED',
  input_type: 'single_choice',
  options: [
    { value: 'channel_a', label: '渠道 A' },
    { value: 'channel_b', label: '渠道 B' },
  ],
  suggestions: [],
  allow_custom_text: true,
  status: 'pending',
};

// ---- 拒答：六 reason_code（AC-12/F22） ----
export const rejectionNotDataQuestion: RejectionPayload = {
  reason_code: 'NOT_DATA_QUESTION',
  reason_text: '这个问题属于原因分析，我不算原因，但可以给你相关的数据。',
  suggestions: [
    { label: '618 各渠道 GMV 排行', question: '618 大促期间各渠道 GMV 是多少，按从高到低排' },
  ],
};

export const rejectionNoMatchingData: RejectionPayload = {
  reason_code: 'NO_MATCHING_DATA',
  reason_text: '平台目前没有「品牌心智份额」这个指标的数据。',
  suggestions: [
    { label: '618 各渠道销售额排行', question: '618 大促期间各渠道销售额是多少' },
  ],
};

export const rejectionCaliberConflict: RejectionPayload = {
  reason_code: 'CALIBER_CONFLICT',
  reason_text: '「退款率」不能同时按订单和按商品两个口径计算，请分开问。',
  suggestions: [{ label: '按订单口径的退款率', question: '618 大促期间按订单口径的退款率是多少' }],
};

export const rejectionGenLintExhausted: RejectionPayload = {
  reason_code: 'GEN_LINT_EXHAUSTED',
  reason_text: '这个问法比较复杂，多次尝试后仍无法生成可靠的查询，请换个问法。',
  suggestions: [
    { label: '618 各渠道 GMV 排行', question: '618 大促期间各渠道 GMV 是多少，按从高到低排' },
  ],
};

export const rejectionQueryTimeout: RejectionPayload = {
  reason_code: 'QUERY_TIMEOUT',
  reason_text: '取数超时了，数据查询时间过长。',
  suggestions: [],
};

export const rejectionQueryError: RejectionPayload = {
  reason_code: 'QUERY_ERROR',
  reason_text: '取数失败，查询执行出现问题。',
  suggestions: [],
};

// ---- error 终态 ----
export const errorLlmUnavailable: ErrorPayload = {
  code: 'E_LLM_UNAVAILABLE',
  message: '大模型服务暂不可用，请稍后重试',
  retryable: true,
};

// ---- SSE 帧序列（AC-4：stage 乱序重复去重 + 终态 + done） ----
export const framesAnswerTurn: SseFrame[] = [
  { event: 'stage', data: { stage: 'understanding', label: '正在理解问题' }, id: '1' },
  { event: 'stage', data: { stage: 'checking_caliber', label: '正在核对口径' }, id: '2' },
  { event: 'stage', data: { stage: 'understanding', label: '正在理解问题' }, id: '3' }, // 同段重复，应去重
  { event: 'stage', data: { stage: 'querying', label: '正在取数' }, id: '4' },
  { event: 'answer', data: 'fixture:answerBar', id: '5' },
  { event: 'done', data: { turn_id: 'turn-0001' }, id: '6' },
];

/** 仅 stage 序列（reducer 单测：乱序/重复） */
export const framesStagesDuplicated: SseFrame[] = [
  { event: 'stage', data: { stage: 'checking_caliber', label: '正在核对口径' }, id: '1' },
  { event: 'stage', data: { stage: 'understanding', label: '正在理解问题' }, id: '2' },
  { event: 'stage', data: { stage: 'checking_caliber', label: '正在核对口径' }, id: '3' },
  { event: 'stage', data: { stage: 'querying', label: '正在取数' }, id: '4' },
  { event: 'stage', data: { stage: 'querying', label: '正在取数' }, id: '5' },
];

export const framesClarificationTurn: SseFrame[] = [
  { event: 'stage', data: { stage: 'understanding', label: '正在理解问题' }, id: '1' },
  { event: 'stage', data: { stage: 'checking_caliber', label: '正在核对口径' }, id: '2' },
  { event: 'clarification', data: 'fixture:clarifySingleChoice', id: '3' },
  { event: 'done', data: { turn_id: 'turn-0001' }, id: '4' },
];

export const framesRejectionTurn: SseFrame[] = [
  { event: 'stage', data: { stage: 'understanding', label: '正在理解问题' }, id: '1' },
  { event: 'stage', data: { stage: 'checking_caliber', label: '正在核对口径' }, id: '2' },
  { event: 'rejection', data: 'fixture:rejectionQueryTimeout', id: '3' },
  { event: 'done', data: { turn_id: 'turn-0001' }, id: '4' },
];

export const framesErrorTurn: SseFrame[] = [
  { event: 'stage', data: { stage: 'understanding', label: '正在理解问题' }, id: '1' },
  { event: 'error', data: 'fixture:errorLlmUnavailable', id: '2' },
  { event: 'done', data: { turn_id: 'turn-0001' }, id: '3' },
];

export const framesCancelledTurn: SseFrame[] = [
  { event: 'stage', data: { stage: 'understanding', label: '正在理解问题' }, id: '1' },
  { event: 'stage', data: { stage: 'querying', label: '正在取数' }, id: '2' },
  { event: 'cancelled', data: { turn_id: 'turn-0001' }, id: '3' },
  { event: 'done', data: { turn_id: 'turn-0001' }, id: '4' },
];

// ---- HTTP 错误信封（409/400/502 等） ----
export const httpErrorValidation: HttpErrorEnvelope = {
  error: { code: 'E_VALIDATION', message: '问题不能为空', retryable: false },
};

export const httpErrorNameConflict: HttpErrorEnvelope = {
  error: {
    code: 'E_NAME_CONFLICT',
    message: '已有同名报表',
    retryable: false,
    existing: { id: 'report-0001', title: '618 各渠道 GMV 排行' },
  },
};

export const httpErrorLlmUnavailable: HttpErrorEnvelope = {
  error: { code: 'E_LLM_UNAVAILABLE', message: '大模型服务暂不可用，请稍后重试', retryable: true },
};

export const httpErrorClarifyExpired: HttpErrorEnvelope = {
  error: { code: 'E_CLARIFY_EXPIRED', message: '该澄清已失效，请重新提问', retryable: false },
};

export const httpErrorNotFound: HttpErrorEnvelope = {
  error: { code: 'E_NOT_FOUND', message: '资源不存在', retryable: false },
};

export const httpErrorInternal: HttpErrorEnvelope = {
  error: { code: 'E_INTERNAL', message: '服务内部错误，请稍后重试', retryable: true },
};

// ---- 请求体样例（三态互斥） ----
export const startTurnQuestion = {
  question: '618 大促期间各渠道 GMV，按从高到低排',
};

export const startTurnClarify = {
  session_id: 'session-0001',
  clarify: { clarify_id: 'clarify-0001', selection: { type: 'option' as const, value: 'beauty_personal_care' } },
};

export const startTurnRecalibrate = {
  session_id: 'session-0001',
  recalibrate: { source_turn_id: 'turn-0001' },
};
