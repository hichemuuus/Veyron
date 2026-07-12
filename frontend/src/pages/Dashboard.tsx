import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { DashboardData, RecentTask, SystemOverview, TaskBrief } from '../api/types'
import { useAppStore } from '../stores/appStore'
import { useAsync } from '../hooks/useAsync'
import { useInterval } from '../hooks/useInterval'
import { Stat, StatusBadge, ProgressMeter, LoadingSpinner, ErrorBox, EmptyState } from '../components/ui'
import { TaskRow } from '../components/task/TaskRow'
import { Sparkline } from '../components/ui/Sparkline'
import { fmtPct, fmtBytes } from '../lib/format'

const REFRESH_MS = 5000
const SPARK_SAMPLES = 40

export function DashboardPage() {
  const { data, loading, error, reload } = useAsync<DashboardData>(() => api.dashboard(), [])
  // Select the stable briefs map reference from the store (no inline mapping —
  // that would return a new array each call and break Zustand's snapshot cache).
  const briefs = useAppStore((s) => s.taskBriefs)
  const recentFromStore = useMemo(() => {
    if (!data?.recent_tasks) return []
    return [...data.recent_tasks]
      .map((t) => briefs[t.public_id] ?? toBrief(t))
      .reverse()
  }, [data, briefs])

  // Refresh periodically (dashboard endpoint is cheap).
  useInterval(reload, REFRESH_MS)

  return (
    <div className="mx-auto max-w-6xl px-8 py-10 page-enter">
      <Hero
        loading={loading && !data}
        active={data?.active_tasks ?? 0}
        total={data?.total_tasks ?? 0}
      />
      {error ? (
        <div className="mt-8">
          <ErrorBox message={error} onRetry={reload} />
        </div>
      ) : null}

      <section className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Active"
          value={loading && !data ? '—' : data?.active_tasks ?? 0}
          tone="active"
          icon={<Pulse />}
          sub={data ? `${data.total_tasks} total` : undefined}
        />
        <Stat
          label="Completed"
          value={loading && !data ? '—' : data?.completed_tasks ?? 0}
          tone="ok"
          icon={<Check />}
        />
        <Stat
          label="Failed"
          value={loading && !data ? '—' : data?.failed_tasks ?? 0}
          tone={data && data.failed_tasks > 0 ? 'fail' : 'default'}
          icon={<Cross />}
        />
        <Stat
          label="Success rate"
          value={loading && !data ? '—' : successRate(data)}
          sub="of finished tasks"
          tone="default"
        />
      </section>

      <section className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RecentTasks
            loading={loading && !data}
            tasks={recentFromStore}
            onRefresh={reload}
          />
        </div>
        <SystemPanel system={data?.system} loading={loading && !data} />
      </section>
    </div>
  )
}

// ── Hero / greeting ──────────────────────────────────────────────────────

function Hero({ loading, active, total }: { loading: boolean; active: number; total: number }) {
  const greeting = greetingForHour()
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0">
        <p className="hud-label text-ink-400">{greeting.eyebrow}</p>
        <h1 className="mt-2 font-display text-display font-medium text-ink-900">
          {greeting.line}
        </h1>
        <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-ink-500">
          {loading
            ? 'Checking on your tasks…'
            : active > 0
            ? `You have ${active} task${active === 1 ? '' : 's'} in progress. I'll keep watch and verify each result.`
            : total > 0
            ? `Everything is settled. Whenever you're ready, describe a new goal and I'll take it from here.`
            : `Nothing here yet. Describe a goal and I'll plan, act, and verify it for you.`}
        </p>
      </div>
      {/* Breathing AI-presence orb — a calm, living focal point. */}
      <div className="hidden shrink-0 sm:block">
        <PresenceOrb active={active > 0} />
      </div>
    </div>
  )
}

function greetingForHour(): { eyebrow: string; line: string } {
  const h = new Date().getHours()
  if (h < 5) return { eyebrow: 'Late night', line: 'Still here.' }
  if (h < 12) return { eyebrow: 'Good morning', line: "Let's make today clear." }
  if (h < 17) return { eyebrow: 'Good afternoon', line: 'What can I take off your plate?' }
  if (h < 21) return { eyebrow: 'Good evening', line: "Let's wind things down." }
  return { eyebrow: 'Good night', line: "I'll keep an eye on things." }
}

function PresenceOrb({ active }: { active: boolean }) {
  return (
    <div className="relative flex h-20 w-20 items-center justify-center">
      <span
        className={`absolute inset-0 rounded-full ${
          active ? 'bg-sig-400/20' : 'bg-ink-300/20'
        } animate-breathe`}
      />
      <span
        className={`absolute inset-2 rounded-full ${
          active ? 'bg-sig-400/25' : 'bg-ink-300/25'
        }`}
      />
      <span
        className={`relative h-12 w-12 rounded-full bg-gradient-to-br from-sig-400 to-sig-600 shadow-card-lg ${
          active ? 'animate-pulseDot' : ''
        }`}
      />
    </div>
  )
}

function successRate(d: DashboardData | null): string {
  if (!d || d.total_tasks === 0) return '—'
  const finished = d.completed_tasks + d.failed_tasks
  if (finished === 0) return '—'
  return fmtPct((d.completed_tasks / finished) * 100)
}

function RecentTasks({
  loading,
  tasks,
  onRefresh,
}: {
  loading: boolean
  tasks: TaskBrief[]
  onRefresh: () => void
}) {
  return (
    <div className="panel flex h-full flex-col p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-lg font-medium text-ink-900">Recent activity</h2>
          <span className="data-mono text-[11px] text-ink-400">{tasks.length}</span>
        </div>
        <button
          onClick={onRefresh}
          className="focus-ring rounded-lg border border-ink-200 bg-white px-2.5 py-1 text-[11px] font-medium text-ink-500 transition-colors hover:bg-ink-50 hover:text-ink-700"
        >
          ↻ Refresh
        </button>
      </div>
      {loading ? (
        <LoadingSpinner label="Loading tasks" />
      ) : tasks.length === 0 ? (
        <EmptyState
          icon="✦"
          title="No tasks yet"
          hint="Describe a goal from the Agent page to get started. I'll plan, act, and verify each step."
          action={
            <Link
              to="/agent"
              className="focus-ring mt-1 rounded-lg bg-sig-500 px-4 py-2 text-xs font-medium text-white shadow-soft transition-all hover:bg-sig-600 active:scale-[0.97]"
            >
              Open Agent →
            </Link>
          }
        />
      ) : (
        <div className="-mr-2 flex max-h-[28rem] flex-col gap-2 overflow-y-auto pr-2">
          {tasks.map((t) => (
            <TaskRow key={t.public_id} task={t} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── System panel with live sparklines ───────────────────────────────────

function SystemPanel({
  system,
  loading,
}: {
  system: SystemOverview | undefined
  loading: boolean
}) {
  // Maintain rolling samples locally; refresh from /system/overview.
  const [cpu, setCpu] = useState<number[]>([])
  const [mem, setMem] = useState<number[]>([])

  const fetchSample = useCallback(async () => {
    try {
      const r = await api.systemOverview()
      const d = r.data
      if (!d) return
      setCpu((p) => [...p.slice(-(SPARK_SAMPLES - 1)), d.cpu_percent])
      setMem((p) => [...p.slice(-(SPARK_SAMPLES - 1)), d.memory_percent])
    } catch {
      // ignore transient polling errors
    }
  }, [])

  // Seed from dashboard system data once, then poll for fresh samples.
  useEffect(() => {
    if (system) {
      setCpu((p) => (p.length ? p : [system.cpu_percent]))
      setMem((p) => (p.length ? p : [system.memory_percent]))
    }
  }, [system])

  useInterval(fetchSample, 2000)

  const s = system
  return (
    <div className="panel flex h-full flex-col p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-lg font-medium text-ink-900">System health</h2>
        <StatusBadge tone={healthTone(s)} label={healthLabel(s)} />
      </div>
      {loading && !s ? (
        <LoadingSpinner label="Reading sensors" />
      ) : s ? (
        <div className="flex flex-1 flex-col gap-3">
          <Metric
            label="Processor"
            value={fmtPct(latest(cpu, s.cpu_percent), 1)}
            tone={latest(cpu, s.cpu_percent) > 85 ? 'warn' : 'default'}
          >
            <Sparkline values={cpu.length ? cpu : [s.cpu_percent]} color="#C75D3A" />
          </Metric>
          <Metric
            label="Memory"
            value={fmtPct(latest(mem, s.memory_percent), 1)}
            tone={latest(mem, s.memory_percent) > 90 ? 'warn' : 'default'}
            sub={`${fmtBytes(s.memory_used)} / ${fmtBytes(s.memory_total)}`}
          >
            <Sparkline values={mem.length ? mem : [s.memory_percent]} color="#715FA0" />
          </Metric>
          <Metric
            label="Storage"
            value={fmtPct(s.disk_percent, 1)}
            tone={s.disk_percent > 90 ? 'warn' : 'default'}
          >
            <div className="mt-1">
              <ProgressMeter percent={s.disk_percent} compact />
            </div>
          </Metric>
          <div className="mt-auto grid grid-cols-2 gap-2 border-t border-ink-200/70 pt-3">
            <MiniStat label="Cores" value={s.cpu_count} />
            <MiniStat label="Uptime" value={uptime(s.boot_time)} />
          </div>
        </div>
      ) : (
        <EmptyState title="No data" hint="Host information unavailable." />
      )}
    </div>
  )
}

function latest(arr: number[], fallback: number): number {
  return arr.length ? arr[arr.length - 1] : fallback
}

function Metric({
  label,
  value,
  sub,
  tone = 'default',
  children,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'default' | 'warn' | 'fail'
  children?: React.ReactNode
}) {
  const toneCls =
    tone === 'warn' ? 'text-warn-600' : tone === 'fail' ? 'text-bad-600' : 'text-ink-900'
  return (
    <div className="rounded-xl border border-ink-200/70 bg-ink-50/60 p-3">
      <div className="flex items-center justify-between">
        <span className="hud-label">{label}</span>
        <span className={`font-display text-base font-medium ${toneCls}`}>{value}</span>
      </div>
      {sub ? <div className="data-mono mt-0.5 text-[10px] text-ink-400">{sub}</div> : null}
      {children ? <div className="mt-2">{children}</div> : null}
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="hud-label">{label}</div>
      <div className="data-mono mt-0.5 text-sm text-ink-700">{value}</div>
    </div>
  )
}

function healthTone(s?: SystemOverview): 'ok' | 'warn' | 'fail' | 'idle' {
  if (!s) return 'idle'
  if (s.cpu_percent > 90 || s.memory_percent > 92 || s.disk_percent > 95) return 'warn'
  return 'ok'
}
function healthLabel(s?: SystemOverview): string {
  if (!s) return 'Unknown'
  return healthTone(s) === 'ok' ? 'Healthy' : 'Stressed'
}

function uptime(boot: number | undefined): string {
  if (!boot) return '—'
  const secs = Math.max(0, Date.now() / 1000 - boot)
  const d = Math.floor(secs / 86400)
  const h = Math.floor((secs % 86400) / 3600)
  if (d > 0) return `${d}d ${h}h`
  const m = Math.floor((secs % 3600) / 60)
  return `${h}h ${m}m`
}

function toBrief(t: RecentTask): TaskBrief {
  return {
    public_id: t.public_id,
    request: t.request,
    status: t.status,
    mode: t.mode,
    result: null,
    error: null,
    created_at: t.created_at,
    started_at: null,
    finished_at: null,
    updated_at: t.updated_at,
    progress: null,
  }
}

// tiny inline icons
function Pulse() {
  return <span className="h-2 w-2 rounded-full bg-sig-500 animate-pulseDot" />
}
function Check() {
  return <span className="text-ok-500">✓</span>
}
function Cross() {
  return <span className="text-bad-500">✕</span>
}
