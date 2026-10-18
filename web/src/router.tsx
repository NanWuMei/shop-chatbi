/**
 * 路由表（SDD §2）：五路由 + / 跳问数 + 未知兜底跳问数。
 * /chat 与 /chat/:sessionId 共用 AskPage（跨路由保活，切换不丢当前问数状态）。
 */
import { Navigate, createBrowserRouter } from 'react-router-dom';
import RequireAuth from './components/layout/RequireAuth';
import Layout from './components/layout/Layout';
import AskPage from './pages/AskPage';
import ReportViewPage from './pages/ReportViewPage';
import ReportsPage from './pages/ReportsPage';
import SessionsPage from './pages/SessionsPage';

/** 路由配置（测试用 createMemoryRouter 复用同一份） */
export const routes = [
  {
    path: '/',
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: 'chat', element: <AskPage /> },
      { path: 'chat/:sessionId', element: <AskPage /> },
      { path: 'reports', element: <ReportsPage /> },
      { path: 'reports/:reportId', element: <ReportViewPage /> },
      { path: 'sessions', element: <SessionsPage /> },
      { path: '*', element: <Navigate to="/chat" replace /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
