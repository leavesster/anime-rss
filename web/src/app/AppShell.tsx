import { useQuery } from "@tanstack/react-query";
import { Activity, BookOpenCheck, Database, Download, Layers3, LayoutDashboard, MoreHorizontal, Radio, Rss, ServerCog, Settings2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { getReadiness, listNotifications } from "../generated/api/client";
import { Button } from "../shared/components/Button";

const navigation = [
  { to: "/", label: "首页", icon: LayoutDashboard, end: true },
  { to: "/feeds", label: "订阅源", icon: Rss },
  { to: "/subscriptions", label: "追番", icon: BookOpenCheck },
  { to: "/downloads", label: "下载", icon: Download },
  { to: "/candidates", label: "单集版本", icon: Layers3 },
  { to: "/releases", label: "种子列表", icon: Database },
  { to: "/operations", label: "运行", icon: ServerCog },
  { to: "/system", label: "系统", icon: Settings2 },
];
const mobilePrimaryPaths = new Set(["/", "/subscriptions", "/candidates", "/downloads"]);
const mobilePrimaryNavigation = [navigation[0], navigation[2], navigation[4], navigation[3]];
const mobileSecondaryNavigation = navigation.filter((item) => !mobilePrimaryPaths.has(item.to));

export function AppShell() {
  const location = useLocation();
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const health = useQuery({ queryKey: ["readiness"], queryFn: getReadiness, refetchInterval: 30_000 });
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: listNotifications, refetchInterval: 30_000 });
  const unread = notifications.data?.filter((item) => !item.read_at).length ?? 0;
  const secondaryActive = mobileSecondaryNavigation.some((item) => location.pathname === item.to || location.pathname.startsWith(`${item.to}/`));

  useEffect(() => setMobileMoreOpen(false), [location.pathname]);

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
              {to === "/system" && unread > 0 && <small className="nav-count" title={`当前载入消息中 ${unread} 条未读`}>{Math.min(unread, 99)}</small>}
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

      {mobileMoreOpen && <div className="mobile-more-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setMobileMoreOpen(false); }}>
        <section className="mobile-more" role="dialog" aria-modal="true" aria-label="更多页面">
          <header><strong>更多页面</strong><Button size="icon" variant="ghost" aria-label="关闭更多页面" title="关闭" icon={<X size={18} />} onClick={() => setMobileMoreOpen(false)} /></header>
          <nav aria-label="更多导航">
            {mobileSecondaryNavigation.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} end={end} to={to} className={({ isActive }) => isActive ? "mobile-more__link mobile-more__link--active" : "mobile-more__link"} onClick={() => setMobileMoreOpen(false)}>
                <Icon size={19} />
                <span>{label}</span>
                {to === "/system" && unread > 0 && <small>{unread} 条未读</small>}
              </NavLink>
            ))}
          </nav>
        </section>
      </div>}

      <nav className="mobile-nav" aria-label="移动端导航">
        {mobilePrimaryNavigation.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} end={end} to={to} className={({ isActive }) => isActive ? "mobile-nav__link mobile-nav__link--active" : "mobile-nav__link"}>
            <Icon size={20} />
            <span>{to === "/candidates" ? "版本" : label}</span>
          </NavLink>
        ))}
        <button type="button" className={mobileMoreOpen || secondaryActive ? "mobile-nav__link mobile-nav__link--active" : "mobile-nav__link"} aria-haspopup="dialog" aria-expanded={mobileMoreOpen} onClick={() => setMobileMoreOpen((open) => !open)}>
          <MoreHorizontal size={20} />
          <span>更多</span>
          {unread > 0 && <small className="mobile-nav__count" title={`当前载入消息中 ${unread} 条未读`}>{Math.min(unread, 99)}</small>}
        </button>
      </nav>
    </div>
  );
}
