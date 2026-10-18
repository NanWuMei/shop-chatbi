/** reportStore：报表列表/详情/刷新临时态（SDD §8）。 */
import { create } from 'zustand';
import { deleteReport, getReport, listReports, refreshReport, renameReport } from '../api/client';
import type { RefreshResponse, ReportDetail, ReportListItem } from '../api/types';

interface ReportState {
  items: ReportListItem[];
  listLoading: boolean;
  listError: string | null;
  q: string;

  detail: ReportDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  /** 刷新临时态：answer 临时替换（快照不变，F28） */
  refreshResult: RefreshResponse | null;
  refreshing: boolean;
  refreshError: string | null;

  loadList(q?: string, opts?: { onError?: (message: string) => void }): Promise<void>;
  setQ(q: string): void;
  loadDetail(reportId: string, opts?: { onError?: (message: string) => void }): Promise<void>;
  refresh(reportId: string, opts?: { onError?: (message: string) => void }): Promise<void>;
  rename(reportId: string, title: string, opts?: { onError?: (message: string) => void }): Promise<boolean>;
  remove(reportId: string, opts?: { onError?: (message: string) => void }): Promise<boolean>;
  clearDetail(): void;
}

export const useReportStore = create<ReportState>((set) => ({
  items: [],
  listLoading: false,
  listError: null,
  q: '',

  detail: null,
  detailLoading: false,
  detailError: null,
  refreshResult: null,
  refreshing: false,
  refreshError: null,

  loadList: async (q, opts) => {
    set({ listLoading: true, listError: null });
    try {
      const resp = await listReports(q ?? '');
      set({ items: resp.items, listLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : '报表加载失败，请重试';
      set({ listLoading: false, listError: message });
      opts?.onError?.(message);
    }
  },

  setQ: (q) => set({ q }),

  loadDetail: async (reportId, opts) => {
    set({ detailLoading: true, detailError: null, detail: null, refreshResult: null });
    try {
      const detail = await getReport(reportId);
      set({ detail, detailLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : '报表加载失败，请重试';
      set({ detailLoading: false, detailError: message });
      opts?.onError?.(message);
    }
  },

  refresh: async (reportId, opts) => {
    set({ refreshing: true, refreshError: null });
    try {
      const result = await refreshReport(reportId);
      set({ refreshResult: result, refreshing: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : '刷新失败，请重试';
      set({ refreshing: false, refreshError: message });
      opts?.onError?.(message);
    }
  },

  rename: async (reportId, title, opts) => {
    try {
      await renameReport(reportId, title);
      // 成功后同步刷新列表行
      set((s) => ({ items: s.items.map((it) => (it.id === reportId ? { ...it, title } : it)) }));
      return true;
    } catch (err) {
      opts?.onError?.(err instanceof Error ? err.message : '操作失败，请重试');
      return false;
    }
  },

  remove: async (reportId, opts) => {
    try {
      await deleteReport(reportId);
      set((s) => ({ items: s.items.filter((it) => it.id !== reportId) }));
      return true;
    } catch (err) {
      opts?.onError?.(err instanceof Error ? err.message : '操作失败，请重试');
      return false;
    }
  },

  clearDetail: () => set({ detail: null, detailError: null, refreshResult: null, refreshError: null }),
}));
