import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { routes } from './router';
import { MockEventSource } from './test/MockEventSource';
import { useChatStore } from './store/chatStore';

// 全部网络走 mock；SSE 用 MockEventSource（工厂内动态导入 fixtures，避免 hoist 引用问题）
vi.mock('./api/client', async () => {
  const actual = await vi.importActual<typeof import('./api/client')>('./api/client');
  const fx = await vi.importActual<typeof import('./test/fixtures')>('./test/fixtures');
  return {
    ...actual,
    getHealth: vi.fn().mockResolvedValue({ status: 'ok', checks: { db: 'ok', llm: 'ok', embedding: 'unconfigured' } }),
    listSessions: vi.fn().mockResolvedValue({ items: fx.sessionListItems }),
    listReports: vi.fn().mockResolvedValue({ items: fx.reportListItems }),
    getMessages: vi.fn().mockResolvedValue({ session: fx.sessionListItems[0], messages: [] }),
    getReport: vi.fn().mockResolvedValue({
      id: 'report-0001',
      title: '618 各渠道 GMV 排行',
      question: '618 大促期间各渠道 GMV，按从高到低排',
      caliber: fx.answerBar.caliber,
      snapshot: { insight: fx.answerBar.insight, chart: fx.answerBar.chart, table: fx.answerBar.table, comparison: null },
      data_time_range: fx.answerBar.data_time_range,
      queried_at: '2026-10-17T10:00:00Z',
      created_at: '2026-10-17T10:05:00Z',
      updated_at: '2026-10-17T10:05:00Z',
    }),
    startTurn: vi.fn().mockResolvedValue({ turn_id: 'turn-0001', session_id: 'session-0001', status: 'running' }),
  };
});

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <RouterProvider router={router} />
      </AntApp>
    </ConfigProvider>,
  );
}

beforeEach(() => {
  MockEventSource.install();
  useChatStore.setState({ sessionId: null, entries: [], draft: '', active: false, closeStream: null });
});

afterEach(() => {
  useChatStore.getState().closeStreamNow();
  MockEventSource.uninstall();
});

describe('路由结构（FR-1/AC-2）', () => {
  it('/ 跳转到 /chat（问数默认首页）', async () => {
    renderAt('/');
    await waitFor(() => expect(screen.getByTestId('composer')).toBeInTheDocument());
  });

  it('三入口导航可达五路由；未知路径兜底到问数', async () => {
    renderAt('/reports');
    await waitFor(() => expect(screen.getByTestId('reports-page')).toBeInTheDocument());
    renderAt('/sessions');
    await waitFor(() => expect(screen.getByTestId('sessions-page')).toBeInTheDocument());
    renderAt('/nope');
    await waitFor(() => expect(screen.getByTestId('composer')).toBeInTheDocument());
  });
});

describe('跨路由保活（AC-2/F6）', () => {
  it('切到 /reports 再回 /chat：输入草稿与消息流不丢', async () => {
    const user = userEvent.setup();
    const { unmount } = renderAt('/chat');
    await waitFor(() => expect(screen.getByTestId('composer-input')).toBeInTheDocument());
    await user.type(screen.getByTestId('composer-input'), '还没发送的草稿');
    unmount();

    const second = renderAt('/reports');
    await waitFor(() => expect(screen.getByTestId('reports-page')).toBeInTheDocument());
    second.unmount();

    renderAt('/chat');
    await waitFor(() => {
      expect((screen.getByTestId('composer-input') as HTMLTextAreaElement).value).toBe('还没发送的草稿');
    });
  });

  it('发送一轮后 URL 会话就绪、消息流保留（问完一轮 URL 就地替换）', async () => {
    const user = userEvent.setup();
    renderAt('/chat');
    await user.type(screen.getByTestId('composer-input'), '618 各渠道 GMV');
    await user.click(screen.getByTestId('composer-send'));
    await waitFor(() => expect(screen.getByTestId('user-bubble')).toBeInTheDocument());
    expect(useChatStore.getState().sessionId).toBe('session-0001');
    // SSE 未推帧前显示过程态
    expect(screen.getByTestId('process-status')).toBeInTheDocument();
  });
});
