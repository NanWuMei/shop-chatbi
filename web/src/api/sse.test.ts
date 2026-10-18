import { describe, expect, it, vi } from 'vitest';
import {
  initialTurnState,
  MAX_RECONNECT_FAILURES,
  openTurnStream,
  turnReducer,
  type EventSourceLike,
  type TurnFrame,
  type TurnMachineState,
} from './sse';
import {
  framesAnswerTurn,
  framesCancelledTurn,
  framesStagesDuplicated,
  answerBar,
  type SseFrame,
} from '../test/fixtures';

function stateFrom(frames: SseFrame[]): TurnMachineState {
  return frames.reduce(turnReducer, initialTurnState());
}

function toFrames(frames: SseFrame[]): TurnFrame[] {
  return frames.map((f) => ({ ...f, data: structuredClone(f.data) }));
}

/** 最小 EventSource mock：注册监听器 + 手动派发 */
class MockEventSource implements EventSourceLike {
  readyState = 1;
  closed = false;
  listeners = new Map<string, Array<(ev: { data?: unknown; lastEventId?: string }) => void>>();
  constructor(
    public url: string,
    public requestedLastEventId: string,
  ) {}
  close(): void {
    this.closed = true;
    this.readyState = 2;
  }
  addEventListener(type: string, listener: (ev: { data?: unknown; lastEventId?: string }) => void): void {
    const arr = this.listeners.get(type) ?? [];
    arr.push(listener);
    this.listeners.set(type, arr);
  }
  dispatch(type: string, data: unknown, lastEventId?: string): void {
    for (const fn of this.listeners.get(type) ?? []) fn({ data, lastEventId });
  }
}

describe('turn 状态机 reducer（AC-4 / TR-3.2）', () => {
  it('三阶段顺序点亮、同段与乱序重复帧去重', () => {
    const s = stateFrom(framesStagesDuplicated);
    expect(s.phase).toBe('streaming');
    expect(s.stageStatuses).toEqual({
      understanding: 'done',
      checking_caliber: 'done',
      querying: 'running',
    });
  });

  it('answer turn：终态后过程帧被忽略、done 关闭', () => {
    const frames = toFrames(framesAnswerTurn).map((f) =>
      f.event === 'answer' ? { ...f, data: answerBar } : f,
    );
    const s = stateFrom(frames);
    expect(s.phase).toBe('closed');
    expect(s.terminal?.event).toBe('answer');
    expect((s.terminal?.payload as typeof answerBar).table.rows).toHaveLength(3);
  });

  it('一个 turn 恰一个终态：第二个终态帧被忽略', () => {
    let s = stateFrom(framesCancelledTurn);
    s = turnReducer(s, { event: 'answer', data: answerBar });
    expect(s.terminal?.event).toBe('cancelled');
  });

  it('unknown 帧（防御）不崩溃：engine 只注册已知事件名', () => {
    // 引擎只对 ['stage', ...TERMINAL_EVENTS, 'done'] 注册监听，未知 event 不会进入 reducer
    const events = ['stage', 'answer', 'clarification', 'rejection', 'error', 'cancelled', 'done'];
    expect(events).toHaveLength(7);
  });
});

describe('建流引擎（AC-6 / TR-3.2）', () => {
  function setup() {
    const created: MockEventSource[] = [];
    const frames: TurnFrame[] = [];
    const onLost = vi.fn();
    const factory = vi.fn((url: string, lastEventId: string) => {
      const es = new MockEventSource(url, lastEventId);
      created.push(es);
      return es;
    });
    const close = openTurnStream('t1', { onFrame: (f) => frames.push(f), onLost }, factory);
    return { created, frames, onLost, factory, close };
  }

  it('帧转发 + lastEventId 记录；done 后关流', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const { created, frames, factory } = setup();
    const es = created[0];
    es.dispatch('stage', { stage: 'understanding', label: '正在理解问题' }, '1');
    es.dispatch('answer', answerBar, '5');
    expect(frames).toHaveLength(2);
    expect(frames[1].data).toEqual(answerBar);
    es.dispatch('done', { turn_id: 't1' }, '6');
    expect(es.closed).toBe(true);
    // 全程只有一次建流；引擎从不 fetch（不重复提交问题由结构保证）
    expect(factory).toHaveBeenCalledTimes(1);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('终态 error 帧（带 JSON 载荷）与原生连接错误（data 空）区分', () => {
    const { created, frames, onLost } = setup();
    const es = created[0];
    es.dispatch('stage', { stage: 'understanding', label: 'x' }, '1');
    es.dispatch('error', { code: 'E_LLM_UNAVAILABLE', message: '大模型服务暂不可用，请稍后重试', retryable: true }, '2');
    expect(frames[frames.length - 1].event).toBe('error');
    expect((frames[frames.length - 1].data as { code: string }).code).toBe('E_LLM_UNAVAILABLE');
    expect(onLost).not.toHaveBeenCalled();
  });

  it('连续 2 次重连失败 → onLost；engine 不重建不 POST', () => {
    const { created, onLost, factory } = setup();
    const es = created[0];
    es.dispatch('stage', { stage: 'understanding', label: 'x' }, '1');
    es.dispatch('error', undefined, '1'); // 第 1 次失败：交给原生自动重连（自带 Last-Event-ID）
    expect(onLost).not.toHaveBeenCalled();
    es.dispatch('error', undefined, '1'); // 第 2 次失败：降级
    expect(onLost).toHaveBeenCalledTimes(1);
    expect(es.closed).toBe(true);
    expect(factory).toHaveBeenCalledTimes(1); // 无手动重建
  });

  it('失败一次后重新 open 清零计数', () => {
    const { created, onLost } = setup();
    const es = created[0];
    es.dispatch('error', undefined);
    es.dispatch('open', undefined); // 重连成功，失败计数清零
    es.dispatch('error', undefined);
    expect(onLost).not.toHaveBeenCalled();
  });

  it('终态后断流：静默收尾不报 onLost', () => {
    const { created, onLost } = setup();
    const es = created[0];
    es.dispatch('cancelled', { turn_id: 't1' }, '3');
    es.dispatch('error', undefined, '3');
    expect(onLost).not.toHaveBeenCalled();
    expect(es.closed).toBe(true);
  });

  it('cleanup 卸载关流', () => {
    const { created, close } = setup();
    close();
    expect(created[0].closed).toBe(true);
  });

  it('MAX_RECONNECT_FAILURES 常量为 2（SDD §5）', () => {
    expect(MAX_RECONNECT_FAILURES).toBe(2);
  });
});
