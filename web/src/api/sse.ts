/**
 * SSE 两段式问数引擎（SDD-前端 §5）：
 * 1. POST /chat/turns 由调用方完成（client.startTurn），本模块只负责建流与状态机；
 * 2. turn 状态机纯 reducer：idle → understanding → checking_caliber → querying → 终态 → closed；
 * 3. 同 stage 去重、乱序重复帧忽略；一个 turn 恰一个终态；
 * 4. 断线重连：原生 EventSource 自动重连自带 Last-Event-ID 头（服务端 10 分钟缓冲按其补帧）；
 *    引擎自行记录 lastEventId 并在工厂签名中透出（自定义工厂/测试可用）；连续 2 次重连失败
 *    降级为 onLost（"连接中断，重试"），全程不重复 POST 问题；
 * 5. 终态后等 done 关流；cleanup() 供卸载/切换会话时关流。
 */
import { API_BASE } from './client';
import { assertNever } from './guard';
import { STAGES, TERMINAL_EVENTS, type Stage, type TerminalEvent } from './types';

// ---------------------------------------------------------------------------
// turn 状态机（纯 reducer，NFR-2）
// ---------------------------------------------------------------------------
export type StageStatus = 'pending' | 'running' | 'done';

export interface TurnMachineState {
  phase: 'idle' | 'streaming' | 'terminal' | 'closed';
  stageStatuses: Record<Stage, StageStatus>;
  terminal: { event: TerminalEvent; payload: unknown } | null;
}

export function initialTurnState(): TurnMachineState {
  return {
    phase: 'idle',
    stageStatuses: { understanding: 'pending', checking_caliber: 'pending', querying: 'pending' },
    terminal: null,
  };
}

export interface TurnFrame {
  /** SSE 事件名：stage | 五终态 | done */
  event: 'stage' | TerminalEvent | 'done';
  data: unknown;
  /** SSE 帧自增 id（Last-Event-ID 载体） */
  id?: string;
}

function isTerminalEvent(event: string): event is TerminalEvent {
  return (TERMINAL_EVENTS as readonly string[]).includes(event);
}

export function turnReducer(state: TurnMachineState, frame: TurnFrame): TurnMachineState {
  if (state.phase === 'closed') return state;
  const { event, data } = frame;

  if (event === 'stage') {
    if (state.phase === 'terminal') return state; // 终态后不再吃过程帧
    const stage = (data as { stage?: string }).stage as Stage | undefined;
    if (!stage || !STAGES.includes(stage)) return state;
    if (state.stageStatuses[stage] === 'running') return state; // 同段去重
    if (state.stageStatuses[stage] === 'done') return state; // 乱序重复忽略
    const next = { ...state.stageStatuses };
    const idx = STAGES.indexOf(stage);
    for (let i = 0; i < idx; i++) next[STAGES[i]] = 'done';
    next[stage] = 'running';
    return { ...state, phase: 'streaming', stageStatuses: next };
  }

  if (isTerminalEvent(event)) {
    if (state.terminal) return state; // 一个 turn 恰一个终态
    const next = { ...state.stageStatuses };
    (Object.keys(next) as Stage[]).forEach((s) => {
      if (next[s] === 'running') next[s] = 'done';
    });
    return { ...state, phase: 'terminal', stageStatuses: next, terminal: { event, payload: data } };
  }

  if (event === 'done') {
    return { ...state, phase: 'closed' };
  }

  return assertNever(event, '未知 SSE 帧类型');
}

// ---------------------------------------------------------------------------
// 建流引擎
// ---------------------------------------------------------------------------
export interface EventSourceLike {
  close(): void;
  readyState: number;
  addEventListener(type: string, listener: (ev: { data?: unknown; lastEventId?: string; readyState?: number }) => void): void;
}

/** (url, lastEventId) → EventSource；原生工厂不额外处理头（自动重连自带 Last-Event-ID） */
export type EventSourceFactory = (url: string, lastEventId: string) => EventSourceLike;

export const MAX_RECONNECT_FAILURES = 2;

export interface StreamHandlers {
  onFrame(frame: TurnFrame): void;
  /** 连续 MAX_RECONNECT_FAILURES 次重连失败（未到终态）→ "连接中断，重试" */
  onLost(): void;
}

export function openTurnStream(
  turnId: string,
  handlers: StreamHandlers,
  factory: EventSourceFactory = (url) => new EventSource(url),
): () => void {
  let disposed = false;
  let es: EventSourceLike;
  let lastEventId = '';
  let failures = 0;
  let sawTerminal = false;

  const handleFrame = (event: string) => (ev: { data?: unknown; lastEventId?: string }) => {
    if (disposed) return;
    if (ev.lastEventId) lastEventId = ev.lastEventId;
    let data: unknown = ev.data;
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data);
      } catch {
        /* 非 JSON 帧原样透传 */
      }
    }
    if (isTerminalEvent(event)) sawTerminal = true;
    handlers.onFrame({ event: event as TurnFrame['event'], data, id: ev.lastEventId });
    if (event === 'done') {
      disposed = true; // 恒为最后一帧，前端据此关闭流（SDD §5.3）
      es.close();
    }
  };

  es = factory(`${API_BASE}/chat/turns/${turnId}/events`, lastEventId);

  es.addEventListener('open', () => {
    failures = 0; // 连上了就清零重连失败计数
  });

  // 注意：终态事件名 error 与 EventSource 原生错误事件同名——
  // 原生错误事件 data 恒为空，终态 error 帧带 JSON 载荷（{code,message,retryable}），据此区分。
  const dataTerminals = TERMINAL_EVENTS.filter((e) => e !== 'error') as TerminalEvent[];
  (['stage', ...dataTerminals, 'done'] as const).forEach((event) => {
    es.addEventListener(event, handleFrame(event));
  });

  es.addEventListener('error', (ev) => {
    if (disposed) return;
    if (ev.data != null) {
      handleFrame('error')(ev); // SSE 终态 error 帧（ChainResult.action=error）
      return;
    }
    if (sawTerminal) {
      // 已有终态只等 done；流断则直接收尾，不提示中断
      disposed = true;
      es.close();
      return;
    }
    failures += 1;
    if (failures >= MAX_RECONNECT_FAILURES) {
      disposed = true;
      es.close();
      handlers.onLost();
    }
    // 其余情况交给原生 EventSource 自动重连（自带 Last-Event-ID），不重复 POST
  });

  return () => {
    disposed = true;
    es.close();
  };
}
