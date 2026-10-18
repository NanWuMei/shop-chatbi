/** 全局布局：顶栏三入口 + 路由出口（SDD §2）。 */
import { Outlet } from 'react-router-dom';
import AppNav from './AppNav';

export default function Layout() {
  return (
    <div className="app-layout">
      <AppNav />
      <main className="app-layout__content">
        <Outlet />
      </main>
    </div>
  );
}
