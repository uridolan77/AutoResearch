import type { PropsWithChildren } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useUIStore } from '../store/uiState'

const navItems = [
  { to: '/', label: 'Create', short: 'C' },
  { to: '/sessions', label: 'Sessions', short: 'S' },
]

export function AppShell({ children }: PropsWithChildren) {
  const { sidebarCollapsed, toggleSidebar } = useUIStore()

  return (
    <div className="app-frame">
      <aside className={`sidebar ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
        <div>
          <Link to="/" className="brand-mark">
            <span className="brand-kicker">AutoResearch</span>
            {!sidebarCollapsed && <strong>Operator Console</strong>}
          </Link>
          <button type="button" className="button button-ghost sidebar-toggle" onClick={toggleSidebar}>
            {sidebarCollapsed ? 'Expand' : 'Collapse'}
          </button>
        </div>
        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav-chip ${isActive ? 'is-active' : ''}`}
            >
              <span className="nav-short">{sidebarCollapsed ? item.short : item.label}</span>
            </NavLink>
          ))}
        </nav>
        {!sidebarCollapsed && (
          <p className="sidebar-note">
            MVP covers ingest, sessions, live detail, and review. Live updates use polling until the WebSocket stream lands.
          </p>
        )}
      </aside>
      <div className="content-shell">
        <header className="topbar">
          <div>
            <p className="eyebrow">Day 11</p>
            <h1>Autonomous improvement, with a human review rail.</h1>
          </div>
          <p className="topbar-note">Backend expected at <code>{(import.meta.env.VITE_API_BASE as string | undefined) || 'http://localhost:8000'}</code></p>
        </header>
        <main className="page-shell">{children}</main>
      </div>
    </div>
  )
}