import type { EventSourceLike } from '../api/sse';

/** 最小 EventSource mock：注册监听器 + 手动派发（引擎只对已知事件名注册） */
export class MockEventSource implements EventSourceLike {
  static instances: MockEventSource[] = [];

  readyState = 1;
  closed = false;
  listeners = new Map<string, Array<(ev: { data?: unknown; lastEventId?: string }) => void>>();

  constructor(
    public url: string,
    public requestedLastEventId = '',
  ) {
    MockEventSource.instances.push(this);
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }

  addEventListener(type: string, listener: (ev: { data?: unknown; lastEventId?: string }) => void): void {
    const arr = this.listeners.get(type) ?? [];
    arr.push(listener);
    this.listeners.set(type, arr);
  }

  dispatch(type: string, data?: unknown, lastEventId?: string): void {
    for (const fn of this.listeners.get(type) ?? []) fn({ data, lastEventId });
  }

  /** 安装为全局 EventSource（jsdom 无此 API），返回最近创建的实例 */
  static install(): void {
    (globalThis as { EventSource?: unknown }).EventSource = MockEventSource;
  }

  static uninstall(): void {
    delete (globalThis as { EventSource?: unknown }).EventSource;
    MockEventSource.instances = [];
  }

  static get last(): MockEventSource | undefined {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }
}
