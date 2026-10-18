/**
 * fetch 封装：base /api/v1、JSON、错误信封 → 类型化 ApiError。
 * 拦截器位：本版不注入 token（SDD §7）；401 分支预留但本版不可达。
 * 13 个接口调用函数（SDD-前端 §4 表）。
 */
import type {
  ContinueSessionResponse,
  HealthResponse,
  HttpErrorEnvelope,
  Message,
  RefreshResponse,
  ReportDetail,
  ReportListItem,
  SaveReportRequest,
  SaveReportResponse,
  SessionMessagesResponse,
  SessionSummary,
  StartTurnRequest,
  TurnStartResponse,
  CancelResponse,
} from './types';

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  /** E_NAME_CONFLICT 附带同名报表信息 */
  readonly existing?: { id: string; title: string };

  constructor(status: number, code: string, message: string, retryable: boolean, existing?: { id: string; title: string }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.existing = existing;
  }
}

// ---- 拦截器位（本版空实现：无 token 注入；401 分支预留） ----
type RequestInterceptor = (init: RequestInit) => RequestInit;
const requestInterceptors: RequestInterceptor[] = [];
export function registerRequestInterceptor(fn: RequestInterceptor): void {
  requestInterceptors.push(fn);
}

function applyInterceptors(init: RequestInit): RequestInit {
  return requestInterceptors.reduce((acc, fn) => fn(acc), init);
}

async function parseErrorBody(response: Response): Promise<HttpErrorEnvelope['error'] | null> {
  try {
    const body = (await response.json()) as Partial<HttpErrorEnvelope>;
    return body.error ?? null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, applyInterceptors(init));

  if (!response.ok) {
    const err = (await parseErrorBody(response)) ?? {
      code: 'E_INTERNAL',
      message: '服务暂时不可用，请稍后重试',
      retryable: true,
    };
    // 401 分支预留：本版后端不会返回（SDD §7）。未来接入登录时在此跳转/刷新 token。
    if (response.status === 401) {
      throw new ApiError(401, err.code, err.message, err.retryable);
    }
    throw new ApiError(response.status, err.code, err.message, err.retryable, err.existing);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

// ---- 问数（F1/F2/F3/F4） ----
export function startTurn(body: StartTurnRequest): Promise<TurnStartResponse> {
  return request<TurnStartResponse>('/chat/turns', jsonInit('POST', body));
}

export function cancelTurn(turnId: string): Promise<CancelResponse> {
  return request<CancelResponse>(`/chat/turns/${turnId}/cancel`, jsonInit('POST'));
}

// ---- 会话与对话记录（F7） ----
export function listSessions(offset = 0, limit = 50): Promise<{ items: SessionSummary[] }> {
  return request<{ items: SessionSummary[] }>(`/sessions?offset=${offset}&limit=${limit}`);
}

export function getMessages(sessionId: string): Promise<SessionMessagesResponse> {
  return request<SessionMessagesResponse>(`/sessions/${sessionId}/messages`);
}

export function deleteSession(sessionId: string): Promise<void> {
  return request<void>(`/sessions/${sessionId}`, { method: 'DELETE' });
}

// ---- 报表（F5/F6） ----
export function saveReport(body: SaveReportRequest): Promise<SaveReportResponse> {
  return request<SaveReportResponse>('/reports', jsonInit('POST', body));
}

export function listReports(q = '', offset = 0, limit = 50): Promise<{ items: ReportListItem[] }> {
  const query = new URLSearchParams({ q, offset: String(offset), limit: String(limit) });
  return request<{ items: ReportListItem[] }>(`/reports?${query.toString()}`);
}

export function getReport(reportId: string): Promise<ReportDetail> {
  return request<ReportDetail>(`/reports/${reportId}`);
}

export function renameReport(reportId: string, title: string): Promise<{ id: string; title: string }> {
  return request<{ id: string; title: string }>(`/reports/${reportId}`, jsonInit('PUT', { title }));
}

export function deleteReport(reportId: string): Promise<void> {
  return request<void>(`/reports/${reportId}`, { method: 'DELETE' });
}

export function refreshReport(reportId: string): Promise<RefreshResponse> {
  return request<RefreshResponse>(`/reports/${reportId}/refresh`, jsonInit('POST'));
}

export function continueSession(reportId: string): Promise<ContinueSessionResponse> {
  return request<ContinueSessionResponse>(`/reports/${reportId}/continue-session`, jsonInit('POST'));
}

// ---- 健康检查（OQ-4 弱探测） ----
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

export type { Message };
