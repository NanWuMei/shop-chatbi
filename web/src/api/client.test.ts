import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  API_BASE,
  ApiError,
  cancelTurn,
  continueSession,
  deleteReport,
  deleteSession,
  getHealth,
  getMessages,
  getReport,
  listReports,
  listSessions,
  refreshReport,
  renameReport,
  saveReport,
  startTurn,
} from '../api/client';
import { httpErrorNameConflict, httpErrorValidation, startTurnClarify, startTurnQuestion, startTurnRecalibrate } from '../test/fixtures';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function okJson(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('api/client 13 接口（TR-3.1）', () => {
  it('startTurn POST /chat/turns 三态请求体', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ turn_id: 't1', session_id: 's1', status: 'running' }, 202));
    await expect(startTurn(startTurnQuestion)).resolves.toMatchObject({ turn_id: 't1' });
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/chat/turns`, expect.objectContaining({ method: 'POST' }));

    fetchMock.mockResolvedValueOnce(okJson({ turn_id: 't1', session_id: 's1', status: 'running' }, 202));
    await startTurn(startTurnClarify);
    const body1 = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body1).toEqual(startTurnClarify);

    fetchMock.mockResolvedValueOnce(okJson({ turn_id: 't1', session_id: 's1', status: 'running' }, 202));
    await startTurn(startTurnRecalibrate);
    const body2 = JSON.parse(fetchMock.mock.calls[2][1].body);
    expect(body2.recalibrate).toEqual({ source_turn_id: 'turn-0001' });
  });

  it('cancelTurn POST cancel', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ turn_id: 't1', status: 'cancelling' }, 202));
    await expect(cancelTurn('t1')).resolves.toMatchObject({ status: 'cancelling' });
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/chat/turns/t1/cancel`);
  });

  it('sessions 三接口', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ items: [] }));
    await listSessions(0, 50);
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/sessions?offset=0&limit=50`);

    fetchMock.mockResolvedValueOnce(okJson({ session: {}, messages: [] }));
    await getMessages('s1');
    expect(fetchMock.mock.calls[1][0]).toBe(`${API_BASE}/sessions/s1/messages`);

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(deleteSession('s1')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[2][0]).toBe(`${API_BASE}/sessions/s1`);
  });

  it('reports 六接口', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ id: 'r1', title: 'x', created_at: '...' }, 201));
    await expect(saveReport({ turn_id: 't1', title: 'x' })).resolves.toMatchObject({ id: 'r1' });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ turn_id: 't1', title: 'x' });

    fetchMock.mockResolvedValueOnce(okJson({ items: [] }));
    await listReports('gmv', 0, 50);
    expect(fetchMock.mock.calls[1][0]).toBe(`${API_BASE}/reports?q=gmv&offset=0&limit=50`);

    fetchMock.mockResolvedValueOnce(okJson({ id: 'r1' }));
    await getReport('r1');
    expect(fetchMock.mock.calls[2][0]).toBe(`${API_BASE}/reports/r1`);

    fetchMock.mockResolvedValueOnce(okJson({ id: 'r1', title: 'y' }));
    await renameReport('r1', 'y');
    expect(fetchMock.mock.calls[3][0]).toBe(`${API_BASE}/reports/r1`);
    expect(fetchMock.mock.calls[3][1].method).toBe('PUT');

    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await deleteReport('r1');
    expect(fetchMock.mock.calls[4][1].method).toBe('DELETE');

    fetchMock.mockResolvedValueOnce(okJson({ action: 'answer' }));
    await refreshReport('r1');
    expect(fetchMock.mock.calls[5][0]).toBe(`${API_BASE}/reports/r1/refresh`);

    fetchMock.mockResolvedValueOnce(okJson({ session_id: 's9' }, 201));
    await expect(continueSession('r1')).resolves.toMatchObject({ session_id: 's9' });
    expect(fetchMock.mock.calls[6][0]).toBe(`${API_BASE}/reports/r1/continue-session`);
  });

  it('health GET /health', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ status: 'ok', checks: { db: 'ok', llm: 'ok', embedding: 'unconfigured' } }));
    await getHealth();
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/health`);
  });
});

describe('错误信封 → ApiError（AC-19 前置）', () => {
  it('400 E_VALIDATION', async () => {
    fetchMock.mockResolvedValueOnce(okJson(httpErrorValidation, 400));
    const err = await startTurn({ question: '' }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('E_VALIDATION');
    expect(err.retryable).toBe(false);
  });

  it('409 E_NAME_CONFLICT 保留 existing', async () => {
    fetchMock.mockResolvedValueOnce(okJson(httpErrorNameConflict, 409));
    const err = await saveReport({ turn_id: 't1', title: '同名' }).catch((e) => e);
    expect(err.code).toBe('E_NAME_CONFLICT');
    expect(err.existing?.id).toBe('report-0001');
  });

  it('非 JSON 错误体兜底', async () => {
    fetchMock.mockResolvedValueOnce(new Response('bad gateway', { status: 502 }));
    const err = await getHealth().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.retryable).toBe(true);
  });
});

describe('拦截器位（AC-19：存在但不注入 token）', () => {
  it('注册后仅加工 init，不出现 Authorization', async () => {
    const { registerRequestInterceptor } = await import('../api/client');
    registerRequestInterceptor((init) => ({ ...init, headers: { ...(init.headers as Record<string, string>) } }));
    fetchMock.mockResolvedValueOnce(okJson({ status: 'ok', checks: { db: 'ok', llm: 'ok', embedding: 'unconfigured' } }));
    await getHealth();
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers['Authorization']).toBeUndefined();
  });
});
