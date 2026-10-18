import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// vitest globals=false：RTL 无法自动注册 cleanup，手动兜底避免用例间 DOM 串扰
afterEach(() => {
  cleanup();
});

// jsdom 环境缺省 API 补齐（EventSource 的 mock 由各测试自注入工厂）
if (typeof window !== 'undefined' && !('scrollTo' in window)) {
  Object.defineProperty(window, 'scrollTo', { value: () => undefined, writable: true });
}

// MessageStream 自动滚底
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => undefined;
}

// AntD 响应式断点依赖
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// ECharts/zrender 需要 2D context：jsdom 未实现 canvas，stub 空实现防未捕获异常
if (typeof HTMLCanvasElement !== 'undefined') {
  const ctx2d = new Proxy(
    { measureText: () => ({ width: 0 }) } as Record<PropertyKey, unknown>,
    {
      get(target, prop: PropertyKey) {
        if (prop in target) return target[prop];
        return () => undefined;
      },
      set() {
        return true;
      },
    },
  );
  HTMLCanvasElement.prototype.getContext = (() => ctx2d) as unknown as typeof HTMLCanvasElement.prototype.getContext;
}
