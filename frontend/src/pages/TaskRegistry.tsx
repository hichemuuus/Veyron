import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { TaskBrief } from '../api/types'
import { useAppStore } from '../stores/appStore'
import { useAsync } from '../hooks/useAsync'
import { useInterval } from '../hooks/useInterval'
import {
  LoadingSpinner,
  ErrorBox,
  EmptyState,
} from '../components/ui'
import { TaskRow } from '../components/task/TaskRow'
import { TASK_STATUS_VALUES, statusInfo } from '../lib/format'

type StatusFilter = 'all' | string
type ModeFilter = 'all' | 'react' | 'plan'

export function TaskRegistryPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [modeFilter, setModeFilter] = useState<ModeFilter>('all')

  const { data, loading, error, reload } = useAsync(
    () => api.listTasks({ limit: 60, status: statusFilter === 'all' ? undefined : statusFilter, mode: modeFilter === 'all' ? undefined : modeFilter }),
    [statusFilter, modeFilter],
  )

  const upsertTasks = useAppStore((s) => s.upsertTasks)
  // Cache fetched tasks into the store so live WS deltas can update them.
  useEffect(() => {
    if (data) upsertTasks(data.tasks)
  }, [data, upsertTasks])

  // Light periodic refresh for tasks that may have transitioned.
  useInterval(reload, 8000)

  const tasks = data?.tasks ?? []
  const counts = useMemoCounts(tasks)

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-100">Task Registry</h1>
          <p className="mt-0.5 text-xs text-ink-400">
            Full history of missions dispatched to the runtime.
          </p>
        </div>
        <button
          onClick={reload}
          className="focus-ring rounded-md border border-ink-700/60 px-3 py-1.5 text-xs text-ink-300 hover:bg-ink-800/60"
        >
          ↻ Refresh
        </button>
      </header>

      {/* status summary strip */}
      <section className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        {TASK_STATUS_VALUES.map((s) => (
          <FilterChip
            key={s}
            active={statusFilter === s}
            onClick={() => setStatusFilter(statusFilter === s ? 'all' : s)}
            label={statusInfo(s).label}
            count={counts[s] ?? 0}
            tone={statusInfo(s).tone}
          />
        ))}
      </section>

      {/* filters */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-md border border-ink-700/60 bg-ink-900/40 p-0.5">
          {(['all', 'react', 'plan'] as ModeFilter[]).map((m) => (
            <button
              key={m}
              onClick={() => setModeFilter(m)}
              className={`focus-ring rounded px-2.5 py-1 font-mono text-[11px] uppercase ${
                modeFilter === m ? 'bg-sig-500/15 text-sig-200' : 'text-ink-400 hover:text-gray-200'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        {statusFilter !== 'all' ? (
          <button
            onClick={() => setStatusFilter('all')}
            className="focus-ring rounded-md border border-ink-700/60 px-2 py-1 text-[11px] text-ink-300 hover:bg-ink-800/60"
          >
            Clear status filter: {statusInfo(statusFilter).label} ×
          </button>
        ) : null}
        <span className="ml-auto font-mono text-[10px] text-ink-500">{tasks.length} shown</span>
      </div>

      <section className="mt-4">
        {error ? (
          <ErrorBox message={error} onRetry={reload} />
        ) : loading && tasks.length === 0 ? (
          <div className="panel">
            <LoadingSpinner label="Loading registry" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="panel">
            <EmptyState
              icon="◎"
              title="No tasks match"
              hint="Try a different status or mode filter, or dispatch a new mission."
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {tasks.map((t) => (
              <TaskRow key={t.public_id} task={t} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function FilterChip({
  label,
  count,
  tone,
  active,
  onClick,
}: {
  label: string
  count: number
  tone: string
  active: boolean
  onClick: () => void
}) {
  const toneText: Record<string, string> = {
    active: 'text-sig-300',
    ok: 'text-ok-400',
    warn: 'text-warn-400',
    fail: 'text-bad-400',
    idle: 'text-ink-300',
  }
  return (
    <button
      onClick={onClick}
      className={`focus-ring panel flex flex-col items-start gap-0.5 p-2 text-left transition-colors ${
        active ? 'border-sig-400/40 bg-sig-500/10 shadow-glow' : 'hover:border-ink-600/80'
      }`}
    >
      <span className="hud-label">{label}</span>
      <span className={`data-mono text-lg font-semibold ${toneText[tone] ?? 'text-gray-100'}`}>
        {count}
      </span>
    </button>
  )
}

function useMemoCounts(tasks: TaskBrief[]): Record<string, number> {
  // Compute counts per status from the current page (not global totals, but
  // useful for the filter strip). Recomputed each render — cheap.
  const out: Record<string, number> = {}
  for (const t of tasks) {
    out[t.status] = (out[t.status] ?? 0) + 1
  }
  return out
}
