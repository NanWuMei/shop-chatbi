import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockEventSource } from '../test/MockEventSource';
import { httpErrorNameConflict, reportListItems, saveReportOk } from '../test/fixtures';
import { useReportStore } from './reportStore';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    listReports: vi.fn(),
    getReport: vi.fn(),
    refreshReport: vi.fn(),
    renameReport: vi.fn(),
    deleteReport: vi.fn(),
    saveReport: vi.fn(),
  };
});

import { getReport, listReports, refreshReport, renameReport, deleteReport, saveReport } from '../api/client';

const listReportsMock = vi.mocked(listReports);
const getReportMock = vi.mocked(getReport);
const refreshReportMock = vi.mocked(refreshReport);
const renameReportMock = vi.mocked(renameReport);
const deleteReportMock = vi.mocked(deleteReport);
const saveReportMock = vi.mocked(saveReport);

beforeEach(() => {
  listReportsMock.mockReset();
  getReportMock.mockReset();
  refreshReportMock.mockReset();
  renameReportMock.mockReset();
  deleteReportMock.mockReset();
  saveReportMock.mockReset();
  useReportStore.setState({ items: [], listLoading: false, listError: null, detail: null, detailLoading: false, detailError: null, refreshResult: null, refreshing: false, refreshError: null });
});

describe('reportStore（FR-17~26/AC-17）', () => {
  it('loadList：拉取列表', async () => {
    listReportsMock.mockResolvedValueOnce({ items: reportListItems });
    await useReportStore.getState().loadList('');
    expect(useReportStore.getState().items).toHaveLength(2);
  });

  it('refresh answer：临时替换渲染态，不动快照', async () => {
    getReportMock.mockResolvedValueOnce({
      id: 'report-0001',
      title: '618 各渠道 GMV 排行',
      question: '618 大促期间各渠道 GMV，按从高到低排',
      caliber: { summary: 's', detail: { metrics: [], dimensions: [], time_range: '', filters: [], comparison: null } },
      snapshot: { insight: '快照解读', chart: null, table: { columns: [], rows: [{ a: 1 }], truncated: false, display_limit: 500 }, comparison: null },
      data_time_range: null,
      queried_at: '2026-10-17T10:00:00Z',
      created_at: '2026-10-17T10:05:00Z',
      updated_at: '2026-10-17T10:05:00Z',
    });
    refreshReportMock.mockResolvedValueOnce({
      action: 'answer',
      question: 'q',
      table: { columns: [], rows: [{ a: 2 }], truncated: false, display_limit: 500 },
      chart: null,
      insight: '刷新解读',
      caliber: { summary: 's', detail: { metrics: [], dimensions: [], time_range: '', filters: [], comparison: null } },
      comparison: null,
      data_time_range: null,
      queried_at: '2026-10-17T12:00:00Z',
      saveable: true,
    });
    await useReportStore.getState().loadDetail('report-0001');
    await useReportStore.getState().refresh('report-0001');
    const s = useReportStore.getState();
    // 临时态生效（F28）
    expect(s.refreshResult?.action).toBe('answer');
    expect((s.refreshResult as { insight: string }).insight).toBe('刷新解读');
    // 快照仍在 detail 中（数据库快照不变）
    expect(s.detail?.snapshot.insight).toBe('快照解读');
  });

  it('refresh 拒答/生成失败/超时：refreshResult 保存 action 原样', async () => {
    const results: Array<{ action: 'query_gen_failed' | 'query_failed' | 'not_answerable'; reason_code: 'GEN_LINT_EXHAUSTED' | 'QUERY_TIMEOUT' | 'NO_MATCHING_DATA'; reason_text: string; suggestions: never[] }> = [
      { action: 'query_gen_failed', reason_code: 'GEN_LINT_EXHAUSTED', reason_text: 'x', suggestions: [] },
      { action: 'query_failed', reason_code: 'QUERY_TIMEOUT', reason_text: 'x', suggestions: [] },
      { action: 'not_answerable', reason_code: 'NO_MATCHING_DATA', reason_text: 'x', suggestions: [] },
    ];
    for (const result of results) {
      refreshReportMock.mockResolvedValueOnce(result);
      await useReportStore.getState().refresh('report-0001');
      expect(useReportStore.getState().refreshResult).toEqual(result);
    }
  });

  it('rename / remove 成功后同步列表', async () => {
    listReportsMock.mockResolvedValue({ items: reportListItems });
    await useReportStore.getState().loadList('');
    renameReportMock.mockResolvedValueOnce({ id: 'report-0001', title: '新名' });
    await expect(useReportStore.getState().rename('report-0001', '新名')).resolves.toBe(true);
    deleteReportMock.mockResolvedValueOnce(undefined);
    await expect(useReportStore.getState().remove('report-0002')).resolves.toBe(true);
    expect(useReportStore.getState().items.map((i) => i.id)).toEqual(['report-0001']);
  });
});

describe('SaveReportDialog 409 冲突流（AC-19）', () => {
  it('saveReport：首存 201；409 时 existing 可读（组件层断言见组件测试）', async () => {
    saveReportMock.mockResolvedValueOnce(saveReportOk);
    await expect(saveReport({ turn_id: 'turn-0001', title: '618 各渠道 GMV 排行' })).resolves.toMatchObject({ id: 'report-0004' });
    saveReportMock.mockRejectedValueOnce(Object.assign(new Error('已有同名报表'), { code: 'E_NAME_CONFLICT', status: 409, retryable: false, existing: httpErrorNameConflict.error.existing }));
    const err = await saveReport({ turn_id: 'turn-0001', title: '618 各渠道 GMV 排行' }).catch((e) => e);
    expect(err.code).toBe('E_NAME_CONFLICT');
    expect(err.existing?.id).toBe('report-0001');
  });
});

afterEach(() => {
  MockEventSource.uninstall();
});
