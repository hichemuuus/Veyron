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
    <div className="mx-auto max-w-7xl px-6 py-6">
      <PageHeader />
      {error ? (
        <div className="mt-6">
          <ErrorBox message={error} onRetry={reload} />
        </div>
      ) : null}

      <section className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
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
          label="Throughput"
          value={loading && !data ? '—' : successRate(data)}
          sub="success rate"
          tone="default"
        />
      </section>

      <section className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
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

function PageHeader() {
  return (
    <div className="flex items-end justify-between">
      <div>
        <h1 className="text-lg font-semibold text-gray-100">Operations Console</h1>
        <p className="mt-0.5 text-xs text-ink-400">
          Real-time view of the autonomous agent runtime and host system.
        </p>
      </div>
      <Link
        to="/agent"
        className="focus-ring rounded-md border border-sig-400/50 bg-sig-500/15 px-3 py-1.5 text-xs font-medium text-sig-200 shadow-glow hover:bg-sig-500/25"
      >
        Launch Agent →
      </Link>
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
    <div className="panel flex h-full flex-col p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="hud-label">Recent Activity</span>
          <span className="data-mono text-[10px] text-ink-500">{tasks.length}</span>
        </div>
        <button
          onClick={onRefresh}
          className="focus-ring rounded border border-ink-700/60 px-2 py-0.5 font-mono text-[10px] text-ink-400 hover:bg-ink-800/60"
        >
          ↻ refresh
        </button>
      </div>
      {loading ? (
        <LoadingSpinner label="Loading tasks" />
      ) : tasks.length === 0 ? (
        <EmptyState
          icon="◎"
          title="No tasks yet"
          hint="Submit a goal from the Agent Workspace to see execution here."
          action={
            <Link
              to="/agent"
              className="focus-ring mt-2 rounded-md border border-sig-400/40 bg-sig-500/10 px-3 py-1.5 text-xs text-sig-200 hover:bg-sig-500/20"
            >
              Open Workspace
            </Link>
          }
        />
      ) : (
        <div className="-mr-1 flex max-h-[26rem] flex-col gap-2 overflow-y-auto pr-1">
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
    <div className="panel flex h-full flex-col p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="hud-label">Host Telemetry</span>
        <StatusBadge tone={healthTone(s)} label={healthLabel(s)} />
      </div>
      {loading && !s ? (
        <LoadingSpinner label="Reading sensors" />
      ) : s ? (
        <div className="flex flex-1 flex-col gap-3">
          <Metric
            label="CPU"
            value={fmtPct(latest(cpu, s.cpu_percent), 1)}
            tone={latest(cpu, s.cpu_percent) > 85 ? 'warn' : 'default'}
          >
            <Sparkline values={cpu.length ? cpu : [s.cpu_percent]} color="#52e6ff" />
          </Metric>
          <Metric
            label="Memory"
            value={fmtPct(latest(mem, s.memory_percent), 1)}
            tone={latest(mem, s.memory_percent) > 90 ? 'warn' : 'default'}
            sub={`${fmtBytes(s.memory_used)} / ${fmtBytes(s.memory_total)}`}
          >
            <Sparkline values={mem.length ? mem : [s.memory_percent]} color="#a98bff" />
          </Metric>
          <Metric
            label="Disk"
            value={fmtPct(s.disk_percent, 1)}
            tone={s.disk_percent > 90 ? 'warn' : 'default'}
          >
            <div className="mt-1">
              <ProgressMeter percent={s.disk_percent} compact />
            </div>
          </Metric>
          <div className="mt-auto grid grid-cols-2 gap-2 border-t border-ink-800/70 pt-3">
            <MiniStat label="Cores" value={s.cpu_count} />
            <MiniStat label="Uptime" value={uptime(s.boot_time)} />
          </div>
        </div>
      ) : (
        <EmptyState title="No telemetry" hint="Host data unavailable." />
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
    tone === 'warn' ? 'text-warn-400' : tone === 'fail' ? 'text-bad-400' : 'text-gray-100'
  return (
    <div className="rounded-lg border border-ink-800/60 bg-ink-900/40 p-2.5">
      <div className="flex items-center justify-between">
        <span className="hud-label">{label}</span>
        <span className={`data-mono text-sm font-semibold ${toneCls}`}>{value}</span>
      </div>
      {sub ? <div className="data-mono mt-0.5 text-[10px] text-ink-500">{sub}</div> : null}
      {children ? <div className="mt-1.5">{children}</div> : null}
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="hud-label">{label}</div>
      <div className="data-mono text-sm text-gray-200">{value}</div>
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
  return healthTone(s) === 'ok' ? 'Nominal' : 'Stressed'
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
  return <span className="h-2 w-2 rounded-full bg-sig-400 animate-pulseDot" />
}
function Check() {
  return <span className="text-ok-400">✓</span>
}
function Cross() {
  return <span className="text-bad-400">✕</span>
}
