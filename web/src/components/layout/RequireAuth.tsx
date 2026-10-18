/**
 * 鉴权包装位（SDD §7）：本版单用户无登录，直接放行。
 * 预留：接入登录后在此校验并重定向，不重构路由结构。
 */
import type { ReactNode } from 'react';

export default function RequireAuth({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
