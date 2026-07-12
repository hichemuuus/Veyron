import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Logo } from '../brand/Logo'
import { ConnectionIndicator } from './ConnectionIndicator'
import { Toasts } from './Toasts'
import { ConfirmationStack } from './ConfirmationStack'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useInterval } from '../../hooks/useInterval'

const NAV = [
  { to: '/', label: 'Home', icon: HomeIcon, end: true },
  { to: '/agent', label: 'Agent', icon: AgentIcon, end: false },
  { to: '/tasks', label: 'Tasks', icon: TasksIcon, end: false },
  { to: '/tools', label: 'Tools', icon: ToolIcon, end: false },
  { to: '/projects', label: 'Projects', icon: ProjectIcon, end: false },
  { to: '/memory', label: 'Memory', icon: MemoryIcon, end: false },
  { to: '/system', label: 'System', icon: SystemIcon, end: false },
]

export function Layout() {
  // Singleton WS bootstrap: connection state + global event routing.
  useWebSocket()

  return (
    <div className="flex h-screen overflow-hidden bg-paper text-ink-900">
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
    <aside className="flex w-60 shrink-0 flex-col border-r border-ink-200/80 bg-paper/80 backdrop-blur">
      <div className="px-5 py-5">
        <Logo />
      </div>
      <nav className="mt-3 flex flex-1 flex-col gap-0.5 px-3">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              `group flex items-center gap-3 border-l-2 px-3 py-2 text-sm transition-all focus-ring ${
                isActive
                  ? 'border-sig bg-surface-2 text-ink-900 font-medium rounded-r-lg'
                  : 'border-transparent text-ink-600 hover:bg-surface-2 hover:text-ink-900 rounded-lg'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <n.icon
                  className={`h-[18px] w-[18px] shrink-0 transition-colors ${
                    isActive ? 'text-sig-600' : 'text-ink-400 group-hover:text-ink-600'
                  }`}
                />
                <span>{n.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="px-3 pb-5">
        <div className="rounded-xl border border-ink-200/70 bg-cream/50 p-3.5">
          <div className="font-display text-sm font-medium text-ink-800">Your companion</div>
          <p className="mt-1 text-[11px] leading-relaxed text-ink-500">
            Describe a goal, and Paios plans, acts, and verifies — then remembers.
          </p>
        </div>
      </div>
    </aside>
  )
}

function Header() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-ink-200/80 bg-paper/70 px-6 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="hud-label text-ink-400">Paios · Personal AI</span>
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

function HomeIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 11l8-6.5 8 6.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 10v9h12v-9" strokeLinecap="round" strokeLinejoin="round" />
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
function TasksIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="4" y="5" width="16" height="15" rx="2.5" />
      <path d="M8 11l2 2 3.5-3.5M8 16h8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
function ToolIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M14.5 6.5a3.5 3.5 0 1 1-4.4 4.4l-5 5a2 2 0 1 0 3 3l5-5a3.5 3.5 0 0 0 4.4-4.4l-2 2-2-2 2-2z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
function ProjectIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M3 7l9-4 9 4-9 4-9-4z" strokeLinejoin="round" />
      <path d="M3 12l9 4 9-4M3 17l9 4 9-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
function MemoryIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M5 5h11a3 3 0 0 1 3 3v11a1 1 0 0 1-1 1H7a2 2 0 0 1-2-2V5z" strokeLinejoin="round" />
      <path d="M9 9h6M9 13h6M9 17h3" strokeLinecap="round" />
    </svg>
  )
}
function SystemIcon({ className }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" strokeLinecap="round" />
    </svg>
  )
}
