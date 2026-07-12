import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type {
  DiskPartition,
  SystemCpu,
  SystemDisk,
  SystemHealth,
  SystemMemory,
  SystemOverview,
  SystemProcess,
} from '../api/types'
import {
  LoadingSpinner,
  ErrorBox,
  EmptyState,
} from '../components/ui'
import { Stat } from '../components/ui/Stat'
import { StatusBadge } from '../components/ui/StatusBadge'
import { Sparkline } from '../components/ui/Sparkline'
import { ProgressMeter } from '../components/ui/ProgressMeter'
import { useInterval } from '../hooks/useInterval'
import { fmtBytes, fmtPct } from '../lib/format'

const SPARK_SAMPLES = 60
const POLL_MS = 2000
const PROC_POLL_MS = 5000

type SortBy = 'cpu' | 'memory'

export function SystemIntelligencePage() {
  const [overview, setOverview] = useState<SystemOverview | null>(null)
  const [cpu, setCpu] = useState<SystemCpu | null>(null)
  const [mem, setMem] = useState<SystemMemory | null>(null)
  const [disk, setDisk] = useState<SystemDisk | null>(null)
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [procs, setProcs] = useState<SystemProcess[]>([])
  const [sortBy, setSortBy] = useState<SortBy>('cpu')
  const [cpuHistory, setCpuHistory] = useState<number[]>([])
  const [memHistory, setMemHistory] = useState<number[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const pollAll = useCallback(async () => {
    try {
      const [ov, c, m, d, h] = await Promise.all([
        api.systemOverview(),
        api.systemCpu(),
        api.systemMemory(),
        api.systemDisk(),
        api.systemHealth(),
      ])
      setError(null)
      if (ov.data) {
        const d = ov.data
        setOverview(d)
        setCpuHistory((p) => [...p.slice(-(SPARK_SAMPLES - 1)), d.cpu_percent])
        setMemHistory((p) => [...p.slice(-(SPARK_SAMPLES - 1)), d.memory_percent])
      }
      if (c.data) setCpu(c.data)
      if (m.data) setMem(m.data)
      if (d.data) setDisk(d.data)
      if (h.data) setHealth(h.data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const pollProcs = useCallback(async () => {
    try {
      const r = await api.systemProcesses(15, sortBy)
      if (r.data) setProcs(r.data.processes)
    } catch {
      // Processes are best-effort.
    }
  }, [sortBy])

  useEffect(() => {
    pollAll()
  }, [pollAll])

  useEffect(() => {
    pollProcs()
  }, [pollProcs])

  useInterval(pollAll, POLL_MS)
  useInterval(pollProcs, PROC_POLL_MS)

  const healthTone = !health ? 'idle' : health.ok ? 'ok' : 'warn'
  const cpuWarn = (overview?.cpu_percent ?? 0) > 85
  const memWarn = (overview?.memory_percent ?? 0) > 90
  const diskWarn = (overview?.disk_percent ?? 0) > 90

  return (
    <div className="mx-auto max-w-6xl px-8 py-8 page-enter">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-display-sm font-medium text-ink-900">System</h1>
          <p className="mt-1 text-sm text-ink-500">
            How the machine is doing — processor, memory, storage, and processes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge tone={healthTone} pulse={!health?.ok} label={health?.ok ? 'Healthy' : health ? 'Issues detected' : 'Unknown'} />
        </div>
      </header>

      {error ? (
        <div className="mt-5">
          <ErrorBox message={error} onRetry={pollAll} />
        </div>
      ) : null}

      {/* Top stat strip */}
      <section className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label="Processor"
          value={loading && !overview ? '—' : fmtPct(overview?.cpu_percent, 1)}
          tone={cpuWarn ? 'warn' : 'default'}
          sub={`${overview?.cpu_count ?? 0} cores`}
          icon={<span className="h-2 w-2 rounded-full bg-sig-500 animate-pulseDot" />}
        />
        <Stat
          label="Memory"
          value={loading && !overview ? '—' : fmtPct(overview?.memory_percent, 1)}
          tone={memWarn ? 'warn' : 'default'}
          sub={overview ? `${fmtBytes(overview.memory_used)} / ${fmtBytes(overview.memory_total)}` : undefined}
        />
        <Stat
          label="Storage"
          value={loading && !overview ? '—' : fmtPct(overview?.disk_percent, 1)}
          tone={diskWarn ? 'warn' : 'default'}
          sub="avg usage"
        />
        <Stat
          label="Uptime"
          value={loading && !overview ? '—' : uptimeStr(overview?.boot_time)}
          tone="default"
        />
      </section>

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* CPU panel */}
        <div className="panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="hud-label">Processor</span>
            <span className="data-mono text-[10px] text-ink-400">
              {cpu ? `${cpu.cores_physical}p / ${cpu.cores_logical}l` : ''}
              {cpu?.freq_mhz_current ? ` · ${Math.round(cpu.freq_mhz_current)} MHz` : ''}
            </span>
          </div>
          {overview ? (
            <>
              <div className="mb-2 flex items-baseline justify-between">
                <span className={`font-display text-3xl font-medium ${cpuWarn ? 'text-warn-600' : 'text-ink-900'}`}>
                  {fmtPct(overview.cpu_percent, 1)}
                </span>
                <span className="font-mono text-[10px] text-ink-400">overall utilization</span>
              </div>
              <Sparkline values={cpuHistory.length ? cpuHistory : [overview.cpu_percent]} color="#C75D3A" />
              {cpu && cpu.per_cpu.length > 0 ? (
                <div className="mt-4 grid grid-cols-4 gap-1.5 sm:grid-cols-6 md:grid-cols-8">
                  {cpu.per_cpu.map((v, i) => (
                    <div
                      key={i}
                      className="flex flex-col items-center rounded-lg border border-ink-200/70 bg-ink-50/60 px-1 py-1.5"
                    >
                      <span className="font-mono text-[9px] text-ink-400">c{i}</span>
                      <span className={`data-mono text-[10px] mt-0.5 ${v > 85 ? 'text-warn-600' : 'text-ink-600'}`}>
                        {Math.round(v)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
              {cpu?.load_avg && cpu.load_avg.length === 3 ? (
                <div className="mt-4 grid grid-cols-3 gap-2 border-t border-ink-200/70 pt-3">
                  <LoadAvg label="1 min" value={cpu.load_avg[0]} cores={cpu.cores_logical} />
                  <LoadAvg label="5 min" value={cpu.load_avg[1]} cores={cpu.cores_logical} />
                  <LoadAvg label="15 min" value={cpu.load_avg[2]} cores={cpu.cores_logical} />
                </div>
              ) : null}
            </>
          ) : (
            <LoadingSpinner label="Reading processor" />
          )}
        </div>

        {/* Memory panel */}
        <div className="panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="hud-label">Memory</span>
            <span className="data-mono text-[10px] text-ink-400">
              {mem ? `swap ${fmtPct(mem.swap_percent, 0)}` : ''}
            </span>
          </div>
          {overview && mem ? (
            <>
              <div className="mb-2 flex items-baseline justify-between">
                <span className={`font-display text-3xl font-medium ${memWarn ? 'text-warn-600' : 'text-ink-900'}`}>
                  {fmtPct(overview.memory_percent, 1)}
                </span>
                <span className="font-mono text-[10px] text-ink-400">
                  {fmtBytes(mem.used)} / {fmtBytes(mem.total)}
                </span>
              </div>
              <Sparkline values={memHistory.length ? memHistory : [overview.memory_percent]} color="#715FA0" />
              <div className="mt-4 grid grid-cols-3 gap-2 border-t border-ink-200/70 pt-3">
                <MemStat label="used" value={fmtBytes(mem.used)} />
                <MemStat label="available" value={fmtBytes(mem.available)} />
                <MemStat label="free" value={fmtBytes(mem.free)} />
              </div>
              {mem.swap_total > 0 ? (
                <div className="mt-4">
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="hud-label">Swap</span>
                    <span className="data-mono text-[10px] text-ink-400">
                      {fmtBytes(mem.swap_used)} / {fmtBytes(mem.swap_total)}
                    </span>
                  </div>
                  <ProgressMeter percent={mem.swap_percent} compact />
                </div>
              ) : null}
            </>
          ) : (
            <LoadingSpinner label="Reading memory" />
          )}
        </div>

        {/* Disk panel */}
        <div className="panel p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <span className="hud-label">Storage</span>
            <span className="data-mono text-[10px] text-ink-400">
              {disk?.partitions.length ?? 0} mount(s)
            </span>
          </div>
          {!disk ? (
            <LoadingSpinner label="Reading storage" />
          ) : disk.partitions.length === 0 ? (
            <EmptyState title="No mounts" hint="No accessible disk partitions." />
          ) : (
            <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
              {disk.partitions.map((p) => (
                <DiskRow key={p.mountpoint} part={p} />
              ))}
            </div>
          )}
        </div>

        {/* Health / warnings panel */}
        <div className="panel p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <span className="hud-label">Health</span>
            <StatusBadge
              tone={healthTone}
              label={health?.ok ? 'No issues' : health ? `${health.issues.length} issue(s)` : 'Unknown'}
            />
          </div>
          {!health ? (
            <LoadingSpinner label="Checking health" />
          ) : health.issues.length === 0 ? (
            <EmptyState icon="✓" title="All clear" hint="No thresholds exceeded." />
          ) : (
            <ul className="flex flex-col gap-2">
              {health.issues.map((issue, i) => (
                <li
                  key={i}
                  className="flex items-start gap-3 rounded-xl border border-warn-500/30 bg-warn-500/5 p-3"
                >
                  <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-warn-500/15 font-mono text-[11px] font-medium text-warn-600">
                    !
                  </span>
                  <span className="text-xs leading-relaxed text-ink-700">{issue}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Top processes */}
        <div className="panel p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <span className="hud-label">Top processes</span>
            <div className="flex items-center gap-1 rounded-lg border border-ink-200 bg-white p-0.5">
              {(['cpu', 'memory'] as SortBy[]).map((s) => (
                <button
                  key={s}
                  onClick={() => setSortBy(s)}
                  className={`focus-ring rounded-md px-2.5 py-1 text-[11px] font-medium uppercase transition-colors ${
                    sortBy === s ? 'bg-sig-500/15 text-sig-700' : 'text-ink-500 hover:text-ink-800'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          {procs.length === 0 ? (
            <EmptyState title="No processes" hint="Process list unavailable." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="hud-label border-b border-ink-200/70">
                    <th className="py-2.5 pr-3 font-medium">PID</th>
                    <th className="py-2.5 pr-3 font-medium">Name</th>
                    <th className="py-2.5 pr-3 font-medium">User</th>
                    <th className="py-2.5 pr-3 text-right font-medium">CPU %</th>
                    <th className="py-2.5 pr-3 text-right font-medium">MEM %</th>
                  </tr>
                </thead>
                <tbody>
                  {procs.map((p) => (
                    <tr key={p.pid} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-50/50">
                      <td className="py-2.5 pr-3 data-mono text-ink-400">{p.pid}</td>
                      <td className="py-2.5 pr-3 font-mono text-ink-700">{p.name || '?'}</td>
                      <td className="py-2.5 pr-3 data-mono text-ink-500">{p.username || '—'}</td>
                      <td
                        className={`py-2.5 pr-3 text-right data-mono ${
                          p.cpu_percent > 50 ? 'text-warn-600' : 'text-ink-600'
                        }`}
                      >
                        {p.cpu_percent.toFixed(1)}
                      </td>
                      <td
                        className={`py-2.5 pr-3 text-right data-mono ${
                          p.memory_percent > 20 ? 'text-warn-600' : 'text-ink-600'
                        }`}
                      >
                        {p.memory_percent.toFixed(1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function uptimeStr(boot: number | undefined | null): string {
  if (!boot) return '—'
  const secs = Math.max(0, Date.now() / 1000 - boot)
  const d = Math.floor(secs / 86400)
  const h = Math.floor((secs % 86400) / 3600)
  if (d > 0) return `${d}d ${h}h`
  const m = Math.floor((secs % 3600) / 60)
  return `${h}h ${m}m`
}

function LoadAvg({ label, value, cores }: { label: string; value: number; cores: number }) {
  const ratio = cores > 0 ? value / cores : 0
  const tone = ratio > 0.9 ? 'text-warn-600' : ratio > 0.6 ? 'text-sig-600' : 'text-ink-600'
  return (
    <div className="flex flex-col">
      <span className="hud-label">{label}</span>
      <span className={`data-mono mt-0.5 text-sm ${tone}`}>{value.toFixed(2)}</span>
    </div>
  )
}

function MemStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="hud-label">{label}</span>
      <span className="data-mono mt-0.5 text-sm text-ink-700">{value}</span>
    </div>
  )
}

function DiskRow({ part }: { part: DiskPartition }) {
  const warn = part.percent > 90
  return (
    <div className="rounded-xl border border-ink-200/70 bg-ink-50/50 p-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-medium text-ink-700">{part.mountpoint}</span>
        <span
          className={`rounded-full border px-1.5 py-px text-[9px] font-medium uppercase ${
            warn
              ? 'border-warn-500/40 text-warn-600 bg-warn-500/10'
              : 'border-ink-300 text-ink-500 bg-ink-100'
          }`}
        >
          {part.fstype}
        </span>
      </div>
      <div className="mt-2.5">
        <ProgressMeter percent={part.percent} compact />
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-ink-400">
        <span>{part.device}</span>
        <span>
          {fmtBytes(part.used)} / {fmtBytes(part.total)} · {fmtBytes(part.free)} free
        </span>
      </div>
    </div>
  )
}
