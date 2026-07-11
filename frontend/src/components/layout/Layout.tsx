import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Logo } from '../brand/Logo'
import { ConnectionIndicator } from './ConnectionIndicator'
import { Toasts } from './Toasts'
import { ConfirmationStack } from './ConfirmationStack'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useInterval } from '../../hooks/useInterval'

const NAV = [
  { to: '/', label: 'Console', icon: ConsoleIcon, end: true },
  { to: '/agent', label: 'Agent Workspace', icon: AgentIcon, end: false },
  { to: '/tasks', label: 'Task Registry', icon: RegistryIcon, end: false },
]

export function Layout() {
  // Singleton WS bootstrap: connection state + global event routing.
  useWebSocket()

  return (
    <div className="flex h-screen overflow-hidden text-gray-100">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
      <Toasts />
      <ConfirmationStack />
    </div>
  )
}

function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-ink-800/80 bg-ink-950/60 backdrop-blur">
      <div className="px-4 py-4">
        <Logo />
      </div>
      <nav className="mt-2 flex flex-1 flex-col gap-1 px-2">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              `group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors focus-ring ${
                isActive
                  ? 'border border-sig-400/30 bg-sig-500/10 text-sig-200 shadow-glow'
                  : 'border border-transparent text-ink-300 hover:bg-ink-850/70 hover:text-gray-100'
              }`
            }
          >
            <n.icon className="h-4 w-4 shrink-0" />
            <span className="font-medium">{n.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-4 py-4">
        <div className="rounded-lg border border-ink-800/70 bg-ink-900/40 p-3">
          <div className="hud-label mb-1">System</div>
          <p className="text-[11px] leading-snug text-ink-400">
            Autonomous agent runtime. Submit a mission, observe execution,
            receive verified results.
          </p>
        </div>
      </div>
    </aside>
  )
}

function Header() {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-ink-800/80 bg-ink-950/40 px-5 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="hud-label">PAIOS · CONTROL CENTER</span>
      </div>
      <div className="flex items-center gap-3">
        <Clock />
        <ConnectionIndicator />
      </div>
    </header>
  )
}

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => setNow(new Date()), []) // initial
  useInterval(() => setNow(new Date()), 1000)
  const time = now.toLocaleTimeString(undefined, { hour12: false })
  const off = -now.getTimezoneOffset() / 60
  const tz = off === 0 ? 'LOCAL' : `UTC${off > 0 ? '+' : ''}${off}`
  return <span className="data-mono text-xs text-ink-400">{time} {tz}</span>
}

// ── Inline nav icons (stroke-based, inherit color) ──────────────────────

type IconProps = { className?: string }

function ConsoleIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="3" y="4" width="18" height="14" rx="2" />
      <path d="M7 9l3 3-3 3M13 15h4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
function AgentIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="12" cy="8" r="3.2" />
      <path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" strokeLinecap="round" />
      <circle cx="12" cy="8" r="0.6" fill="currentColor" />
    </svg>
  )
}
function RegistryIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
      <circle cx="7" cy="6" r="0.8" fill="currentColor" />
      <circle cx="11" cy="12" r="0.8" fill="currentColor" />
      <circle cx="9" cy="18" r="0.8" fill="currentColor" />
    </svg>
  )
}
