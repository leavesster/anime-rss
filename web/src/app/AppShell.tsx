import { useQuery } from "@tanstack/react-query";
import { Activity, BookOpenCheck, Database, Layers3, LayoutDashboard, Radio, Rss } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { getReadiness } from "../generated/api/client";

const navigation = [
  { to: "/", label: "概览", icon: LayoutDashboard, end: true },
  { to: "/feeds", label: "订阅源", icon: Rss },
  { to: "/subscriptions", label: "追番", icon: BookOpenCheck },
  { to: "/candidates", label: "剧集候选", icon: Layers3 },
  { to: "/releases", label: "发布条目", icon: Database },
];

export function AppShell() {
  const health = useQuery({ queryKey: ["readiness"], queryFn: getReadiness, refetchInterval: 30_000 });

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark"><Radio size={21} /></span>
          <div><strong>Anime RSS</strong><span>自动追番服务</span></div>
        </div>
        <nav aria-label="主导航">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} end={end} to={to} className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__status">
          <span className={`connection-dot ${health.isSuccess ? "connection-dot--online" : ""}`} />
          <div><strong>{health.isSuccess ? "服务运行正常" : "正在连接服务"}</strong><span>本地实例 · v0.1.0</span></div>
        </div>
      </aside>

      <main className="app-main">
        <div className="mobile-header">
          <div className="brand brand--mobile"><span className="brand__mark"><Radio size={19} /></span><strong>Anime RSS</strong></div>
          <span className="mobile-health"><Activity size={16} />{health.isSuccess ? "正常" : "连接中"}</span>
        </div>
        <div className="page-container"><Outlet /></div>
      </main>

      <nav className="mobile-nav" aria-label="移动端导航">
        {navigation.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} end={end} to={to} className={({ isActive }) => isActive ? "mobile-nav__link mobile-nav__link--active" : "mobile-nav__link"}>
            <Icon size={20} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
