/** 顶栏三入口：问数 / 报表 / 对话记录（默认问数，SDD §2）。含 /health 弱探测（OQ-4）。 */
import { Tag } from 'antd';
import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { getHealth } from '../../api/client';

const items = [
  { to: '/chat', label: '问数' },
  { to: '/reports', label: '报表' },
  { to: '/sessions', label: '对话记录' },
];

export default function AppNav() {
  const navigate = useNavigate();
  const [degraded, setDegraded] = useState(false);

  useEffect(() => {
    let alive = true;
    // /health 首屏弱探测：degraded 非阻断提示；探测失败静默不阻塞（OQ-4）
    getHealth()
      .then((h) => {
        if (alive) setDegraded(h.status === 'degraded');
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  return (
    <header className="app-nav">
      <span
        className="app-nav__logo"
        role="button"
        tabIndex={0}
        onClick={() => navigate('/chat')}
        onKeyDown={(e) => e.key === 'Enter' && navigate('/chat')}
      >
        ChatBI
      </span>
      <nav className="app-nav__links">
        {items.map((it) => (
          <NavLink key={it.to} to={it.to} className={({ isActive }) => (isActive ? 'app-nav__link app-nav__link--active' : 'app-nav__link')}>
            {it.label}
            {it.to === '/chat' && degraded && (
              <Tag color="warning" style={{ marginLeft: 6, marginBottom: 0 }} title="部分依赖服务暂不可用，问数功能可能受影响">
                服务降级
              </Tag>
            )}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
