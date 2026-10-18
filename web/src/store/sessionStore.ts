/** sessionStore：对话记录列表（SDD §8）。 */
import { create } from 'zustand';
import { deleteSession, listSessions } from '../api/client';
import type { SessionSummary } from '../api/types';

interface SessionState {
  items: SessionSummary[];
  loading: boolean;
  error: string | null;

  load(opts?: { onError?: (message: string) => void }): Promise<void>;
  remove(sessionId: string, opts?: { onError?: (message: string) => void }): Promise<boolean>;
}

export const useSessionStore = create<SessionState>((set) => ({
  items: [],
  loading: false,
  error: null,

  load: async (opts) => {
    set({ loading: true, error: null });
    try {
      const resp = await listSessions();
      set({ items: resp.items, loading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : '会话加载失败，请重试';
      set({ loading: false, error: message });
      opts?.onError?.(message);
    }
  },

  remove: async (sessionId, opts) => {
    try {
      await deleteSession(sessionId);
      set((s) => ({ items: s.items.filter((it) => it.id !== sessionId) }));
      return true;
    } catch (err) {
      opts?.onError?.(err instanceof Error ? err.message : '操作失败，请重试');
      return false;
    }
  },
}));
