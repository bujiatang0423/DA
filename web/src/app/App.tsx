import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import type { FeatureDefinition } from "./featureRegistry";

const icons: Record<string, string> = {
  candidates: "◈",
  holdings: "▣",
  maintenance: "✎",
  backtests: "◒",
  runs: "☷",
};

export function App({ features }: { features: readonly FeatureDefinition[] }): JSX.Element {
  const location = useLocation();
  const active = features.find((feature) => location.pathname.startsWith(feature.path));
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">盾</div>
          <div><strong>四维盾剑</strong><span>DA 研究平台</span></div>
        </div>
        <div className="sidebar-caption">工作台</div>
        <nav className="sidebar-nav" aria-label="主导航">
          {features.map((feature) => (
            <NavLink
              className={({ isActive }) => `nav-item ${isActive ? "nav-item-active" : ""}`}
              key={feature.id}
              to={feature.path}
            >
              <span className="nav-icon">{icons[feature.id] ?? "•"}</span>
              <span>{feature.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="online-dot" />
          <span>研究服务</span>
          <span className="muted">v2.12</span>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div><span className="breadcrumb">工作台 / </span><strong>{active?.label ?? "概览"}</strong></div>
          <div className="topbar-meta"><span className="status-dot" /> 数据链路正常 <span className="date-chip">点时数据 · Asia/Shanghai</span></div>
        </header>
        <div className="content-area"><Routes>{features.map((feature) => <Route key={feature.id} path={feature.path} element={feature.element} />)}</Routes></div>
      </main>
    </div>
  );
}
