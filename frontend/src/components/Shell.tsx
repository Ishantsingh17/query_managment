import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  BarChart3, Bell, ChevronDown, CircleCheck, FileText, Inbox, LayoutGrid, LifeBuoy, LogOut, Search, Settings, ShieldCheck, Stamp,
} from 'lucide-react'
import { useAuth } from '../lib/auth'
import { useApi, useDebounced } from '../lib/hooks'
import type { Paged, RequestRow, Summary } from '../lib/types'
import { fmtShort, fmtTime } from '../lib/format'
import { StatusChip } from './ui'

interface NavDef { to: string; label: string; icon: React.ReactNode; badge?: number }

export default function Shell() {
  const { user } = useAuth()
  const { data: summary } = useApi<Summary>('/api/dashboard/summary', { poll: 15000 })
  const { data: status } = useApi<{ operational: boolean; connected: number; total: number }>('/api/system/status', { poll: 30000 })
  if (!user) return null

  const ic = { size: 19, strokeWidth: 1.9 }
  const workspace: NavDef[] =
    user.role === 'VALIDATOR'
      ? [
          { to: '/queue', label: 'Review Queue', icon: <Inbox {...ic} />, badge: summary?.badges.review_queue },
          { to: '/requests', label: 'Requests', icon: <FileText {...ic} /> },
          { to: '/completed', label: 'Completed', icon: <CircleCheck {...ic} /> },
        ]
      : user.role === 'SME'
        ? [
            { to: '/dashboard', label: 'Dashboard', icon: <LayoutGrid {...ic} /> },
            { to: '/approvals', label: 'Approvals', icon: <Stamp {...ic} />, badge: summary?.badges.approvals },
            { to: '/completed', label: 'Completed', icon: <CircleCheck {...ic} /> },
          ]
        : [
            { to: '/dashboard', label: 'Dashboard', icon: <LayoutGrid {...ic} /> },
            { to: '/requests', label: 'Requests', icon: <FileText {...ic} /> },
            { to: '/completed', label: 'Completed', icon: <CircleCheck {...ic} /> },
          ]
  const general: NavDef[] = [
    { to: '/reports', label: 'Reports', icon: <BarChart3 {...ic} /> },
    { to: '/settings', label: 'Settings', icon: <Settings {...ic} /> },
    { to: '/help', label: 'Help Center', icon: <LifeBuoy {...ic} /> },
  ]

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo"><ShieldCheck size={20} strokeWidth={2.2} /></div>
          <div>
            <div className="brand-name">Audit Evidence</div>
            <div className="brand-sub">Platform</div>
          </div>
        </div>
        <div className="nav-section">Workspace</div>
        <nav className="nav-list">
          {workspace.map((n) => <NavItem key={n.to} {...n} />)}
        </nav>
        <div className="nav-section">General</div>
        <nav className="nav-list">
          {general.map((n) => <NavItem key={n.to} {...n} />)}
        </nav>
        <div className="sys-status">
          <div className="sys-status-title">
            <span className={`dot ${status?.operational === false ? 'amber' : 'green'}`} />
            {status?.operational === false ? 'Degraded — source outage' : 'All systems operational'}
          </div>
          <div className="sys-status-sub">{status ? `${status.connected} source systems connected` : 'Checking source systems…'}</div>
        </div>
      </aside>
      <div className="main">
        <Topbar />
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function NavItem({ to, label, icon, badge }: NavDef) {
  return (
    <NavLink to={to} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
      {icon}
      <span>{label}</span>
      {!!badge && <span className="nav-badge">{badge}</span>}
    </NavLink>
  )
}

function Topbar() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const [menu, setMenu] = useState<'user' | 'bell' | null>(null)
  const [q, setQ] = useState('')
  const [focused, setFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const dq = useDebounced(q, 250)
  const { data: results } = useApi<Paged<RequestRow>>(dq.trim().length >= 2 ? `/api/requests?view=all&search=${encodeURIComponent(dq)}&page_size=6` : null)
  const { data: notes } = useApi<{ id: string; title: string; request_id: string; link: string; sent_at: string }[]>('/api/notifications', { poll: 20000 })
  const recent = (notes ?? []).filter((n) => Date.now() - new Date(n.sent_at).getTime() < 3 * 86400000)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menu])

  if (!user) return null
  const openRequest = (rid: string) => {
    setQ('')
    nav(user.role === 'VALIDATOR' ? `/queue/${rid}` : user.role === 'SME' ? `/approvals/${rid}` : `/requests/${rid}`)
  }

  return (
    <header className="topbar">
      <div className="global-search">
        <Search size={16} />
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search requests, vendors, documents..."
               onFocus={() => setFocused(true)} onBlur={() => window.setTimeout(() => setFocused(false), 150)} />
        <span className="kbd">⌘K</span>
        {focused && dq.trim().length >= 2 && (
          <div className="search-results">
            {results?.items.length ? results.items.map((r) => (
              <button key={r.request_id} onMouseDown={() => openRequest(r.request_id)}>
                <span><span className="id-link">{r.request_id}</span> <span className="muted">· {r.query_type_label}</span></span>
                <StatusChip status={r.status} label={r.status_label} />
              </button>
            )) : <div className="muted" style={{ padding: 10 }}>No matching requests.</div>}
          </div>
        )}
      </div>
      <div className="topbar-right">
        <div style={{ position: 'relative' }}>
          <button className="icon-btn" aria-label="Notifications" onClick={(e) => { e.stopPropagation(); setMenu(menu === 'bell' ? null : 'bell') }}>
            <Bell size={17} />
            {recent.length > 0 && <span className="bell-dot" />}
          </button>
          {menu === 'bell' && (
            <div className="menu" style={{ minWidth: 300 }} onClick={(e) => e.stopPropagation()}>
              <div className="menu-head"><strong>Notifications</strong></div>
              {(notes ?? []).length === 0 && <div className="muted" style={{ padding: 10 }}>You're all caught up.</div>}
              {(notes ?? []).map((n) => (
                <button key={n.id} className="menu-item" onClick={() => { setMenu(null); nav(n.link) }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{n.title}</div>
                    <div className="muted" style={{ fontSize: 12 }}>{n.request_id} · {fmtShort(n.sent_at)} {fmtTime(n.sent_at)}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="user-pill" onClick={(e) => { e.stopPropagation(); setMenu(menu === 'user' ? null : 'user') }}>
          <div className="avatar">{user.initials}</div>
          <div>
            <div className="user-name">{user.full_name}</div>
            <div className="user-title">{user.title}</div>
          </div>
          <ChevronDown size={16} className="muted" />
          {menu === 'user' && (
            <div className="menu" onClick={(e) => e.stopPropagation()}>
              <div className="menu-head">
                <div style={{ fontWeight: 600 }}>{user.full_name}</div>
                <div className="muted" style={{ fontSize: 12 }}>{user.email}</div>
              </div>
              <button className="menu-item" onClick={() => { setMenu(null); nav('/settings') }}><Settings size={15} /> Settings</button>
              <button className="menu-item" onClick={() => { logout(); nav('/login') }}><LogOut size={15} /> Sign out</button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
