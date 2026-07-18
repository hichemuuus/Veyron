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
    <div className="mx-auto max-w-6xl px-8 py-8 page-enter">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-display-sm font-medium text-ink-900">Tasks</h1>
          <p className="mt-1 text-sm text-ink-500">
            Everything you've asked me to do.
          </p>
        </div>
        <button
          onClick={reload}
          className="focus-ring rounded-lg border border-ink-200 bg-ink-100 px-3.5 py-2 text-xs font-medium text-ink-400 transition-colors hover:bg-ink-200"
        >
          ↻ Refresh
        </button>
      </header>

      {/* status summary strip */}
      <section className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
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
        <div className="flex items-center gap-1 rounded-lg border border-ink-200 bg-ink-200/40 p-0.5">
          {(['all', 'react', 'plan'] as ModeFilter[]).map((m) => (
            <button
              key={m}
              onClick={() => setModeFilter(m)}
              className={`focus-ring rounded-md px-2.5 py-1 text-[11px] font-medium uppercase transition-colors ${
                modeFilter === m ? 'bg-sig-500/15 text-sig-700' : 'text-ink-500 hover:bg-ink-100/60 hover:text-ink-700'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        {statusFilter !== 'all' ? (
          <button
            onClick={() => setStatusFilter('all')}
            className="focus-ring rounded-lg border border-ink-200 bg-ink-100 px-2.5 py-1.5 text-[11px] font-medium text-ink-500 transition-colors hover:bg-ink-200"
          >
            Clear: {statusInfo(statusFilter).label} ×
          </button>
        ) : null}
        <span className="ml-auto font-mono text-[10px] text-ink-400">{tasks.length} shown</span>
      </div>

      <section className="mt-5">
        {error ? (
          <ErrorBox message={error} onRetry={reload} />
        ) : loading && tasks.length === 0 ? (
          <div className="panel">
            <LoadingSpinner label="Loading tasks" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="panel">
            <EmptyState
              icon="✦"
              title="No tasks match"
              hint="Try a different status or mode filter, or start something new."
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
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
    active: 'text-sig-600',
    ok: 'text-ok-600',
    warn: 'text-warn-600',
    fail: 'text-bad-600',
    idle: 'text-ink-600',
  }
  return (
    <button
      onClick={onClick}
      className={`focus-ring flex flex-col items-start gap-1 rounded-xl border p-3 text-left transition-all ${
        active
          ? 'border-sig-500/40 bg-sig-50 shadow-soft'
          : 'border-ink-200/70 bg-ink-100 hover:border-ink-300 hover:bg-ink-200'
      }`}
    >
      <span className="hud-label">{label}</span>
      <span className={`font-display text-2xl font-medium tracking-tight ${toneText[tone] ?? 'text-ink-900'}`}>
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
