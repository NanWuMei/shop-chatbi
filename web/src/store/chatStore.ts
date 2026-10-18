/**
 * chatStore：当前会话、消息流、turn 阶段（SDD §8）。
 * 跨路由保活：store 常驻内存，切走再回不丢当前会话与输入草稿（AC-2/F6）。
 */
import { create } from 'zustand';
import { cancelTurn, getMessages, startTurn } from '../api/client';
import { initialTurnState, openTurnStream, turnReducer, type TurnMachineState } from '../api/sse';
import type { ClarifyPayload, Message, MessagePayload, StartTurnRequest, TerminalEvent } from '../api/types';
import { assertNever } from '../api/guard';

/** 澄清确认的 selection（option | time_preset | custom） */
export type ClarifySelection = NonNullable<StartTurnRequest['clarify']>['selection'];

/** 消息流条目：用户气泡 / 进行中 turn / 终态（历史还原）/ note */
export type ChatEntry =
  | { kind: 'user'; id: string; question: string }
  | { kind: 'turn'; id: string; turnId: string; machine: TurnMachineState; connectionLost: boolean }
  | { kind: 'terminal'; id: string; event: TerminalEvent; payload: MessagePayload }
  | { kind: 'note'; id: string; text: string; href?: string };

let entrySeq = 0;
const nextId = (): string => `entry-${++entrySeq}`;

interface RunTurnOptions {
  onSessionReady?: (sessionId: string) => void;
  /** POST 202 成功（建流前）回调：如把澄清卡就地收起 */
  onStart?: () => void;
  onError?: (message: string) => void;
}

interface ChatState {
  sessionId: string | null;
  entries: ChatEntry[];
  /** 输入框草稿（跨路由保活） */
  draft: string;
  /** 活动互斥：一轮一个进行中 turn */
  active: boolean;
  /** 关闭当前流（卸载/切换会话时调用） */
  closeStream: (() => void) | null;

  setDraft(draft: string): void;
  ask(question: string, opts?: RunTurnOptions): void;
  confirmClarify(payload: ClarifyPayload, selection: ClarifySelection, opts?: RunTurnOptions): void;
  recalibrate(sourceTurnId: string, opts?: RunTurnOptions): void;
  cancelActiveTurn(): void;
  /** 澄清卡「取消」就地收起：不发请求（FR-11） */
  cancelClarify(clarifyId: string): void;
  /** 系统性 note 条目（如"已存为报表：《名称》"，可带跳转链接，FR-16） */
  addNote(text: string, href?: string): void;
  loadSession(sessionId: string, opts?: { onError?: (message: string) => void }): Promise<void>;
  closeStreamNow(): void;
  reset(): void;
}

function messageToEntry(m: Message): ChatEntry {
  const payload = m.payload;
  switch (m.type) {
    case 'user':
      return { kind: 'user', id: m.id, question: (payload as { question: string }).question };
    case 'clarification':
      return { kind: 'terminal', id: m.id, event: 'clarification', payload };
    case 'answer':
      return { kind: 'terminal', id: m.id, event: 'answer', payload };
    case 'rejection':
      return { kind: 'terminal', id: m.id, event: 'rejection', payload };
    case 'note':
      return { kind: 'note', id: m.id, text: (payload as { text: string }).text };
    default:
      return assertNever(m.type, '未知消息类型');
  }
}

function markClarifySubmitted(entries: ChatEntry[], clarifyId: string, status: 'confirmed' | 'cancelled'): ChatEntry[] {
  return entries.map((e) => {
    if (e.kind === 'terminal' && e.event === 'clarification') {
      const payload = e.payload as ClarifyPayload;
      if (payload.clarify_id === clarifyId) {
        return { ...e, payload: { ...payload, status } };
      }
    }
    return e;
  });
}

export const useChatStore = create<ChatState>((set, get) => {
  /** 统一的两段式建流：POST 成功后 openTurnStream，帧驱动 machine */
  const runTurn = (body: StartTurnRequest, opts?: RunTurnOptions): void => {
    if (get().active) return;
    set({ active: true });
    startTurn(body)
      .then((resp) => {
        const turnId = resp.turn_id;
        const sessionChanged = get().sessionId !== resp.session_id;
        set({ sessionId: resp.session_id });
        if (sessionChanged) opts?.onSessionReady?.(resp.session_id);
        opts?.onStart?.();

        get().closeStreamNow();
        const entryId = nextId();
        set((s) => ({
          entries: [...s.entries, { kind: 'turn', id: entryId, turnId, machine: initialTurnState(), connectionLost: false }],
        }));

        const close = openTurnStream(turnId, {
          onFrame: (frame) => {
            set((s) => ({
              entries: s.entries.map((e) => {
                if (e.kind !== 'turn' || e.id !== entryId) return e;
                const machine = turnReducer(e.machine, frame);
                return { ...e, machine };
              }),
            }));
            // done 帧（phase=closed）后解锁互斥
            const entry = get().entries.find((e) => e.kind === 'turn' && e.id === entryId);
            if (entry && entry.kind === 'turn' && entry.machine.phase === 'closed') {
              set({ active: false, closeStream: null });
            }
          },
          onLost: () => {
            set((s) => ({
              entries: s.entries.map((e) => (e.kind === 'turn' && e.id === entryId ? { ...e, connectionLost: true } : e)),
            }));
            set({ active: false });
          },
        });
        set({ closeStream: close });
      })
      .catch((err: unknown) => {
        set({ active: false });
        const message = err instanceof Error ? err.message : '发起提问失败，请重试';
        opts?.onError?.(message);
      });
  };

  return {
    sessionId: null,
    entries: [],
    draft: '',
    active: false,
    closeStream: null,

    setDraft: (draft) => set({ draft }),

    ask: (question, opts) => {
      // 乐观渲染用户气泡（FR-4）：先上屏再发请求
      set((s) => ({ entries: [...s.entries, { kind: 'user', id: nextId(), question }] }));
      runTurn(
        { question, ...(get().sessionId ? { session_id: get().sessionId as string } : {}) },
        opts,
      );
    },

    confirmClarify: (payload, selection, opts) =>
      runTurn(
        { session_id: get().sessionId ?? undefined, clarify: { clarify_id: payload.clarify_id, selection } },
        {
          ...opts,
          // POST 202 成功后才把澄清卡就地收起；失败保持可交互（FR-11）
          onStart: () => {
            set((s) => ({ entries: markClarifySubmitted(s.entries, payload.clarify_id, 'confirmed') }));
            opts?.onStart?.();
          },
        },
      ),

    recalibrate: (sourceTurnId, opts) =>
      runTurn({ session_id: get().sessionId ?? undefined, recalibrate: { source_turn_id: sourceTurnId } }, opts),

    cancelActiveTurn: () => {
      const running = [...get().entries].reverse().find((e) => e.kind === 'turn' && e.machine.phase !== 'closed');
      if (running && running.kind === 'turn') {
        // cancel 接口失败静默：以流终态为准（FR-7）
        cancelTurn(running.turnId).catch(() => undefined);
      }
    },

    cancelClarify: (clarifyId) => {
      set((s) => ({ entries: markClarifySubmitted(s.entries, clarifyId, 'cancelled') }));
    },

    addNote: (text, href) => {
      set((s) => ({ entries: [...s.entries, { kind: 'note', id: nextId(), text, href }] }));
    },

    loadSession: async (sessionId, opts) => {
      get().closeStreamNow();
      set({ sessionId, active: false });
      try {
        const resp = await getMessages(sessionId);
        set({ entries: resp.messages.map((m) => messageToEntry(m)) });
      } catch (err) {
        opts?.onError?.(err instanceof Error ? err.message : '加载会话失败，请重试');
      }
    },

    closeStreamNow: () => {
      get().closeStream?.();
      set({ closeStream: null });
    },

    reset: () => {
      get().closeStreamNow();
      set({ sessionId: null, entries: [], draft: '', active: false });
    },
  };
});
