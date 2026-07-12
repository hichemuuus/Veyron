import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { ExecutionStep, TaskDetail as TaskDetailT, TimelineResponse } from '../api/types'
import { useAppStore } from '../stores/appStore'
import { getWsClient } from '../api/websocket'
import { useAsync } from '../hooks/useAsync'
import { useInterval } from '../hooks/useInterval'
import {
  StatusBadge,
  ProgressMeter,
  Stat,
  LoadingSpinner,
  ErrorBox,
  EmptyState,
  Button,
} from '../components/ui'
import { LiveTimeline } from '../components/timeline/LiveTimeline'
import {
  fmtMs,
  fmtRelative,
  fmtClock,
  isActiveStatus,
  isTerminalStatus,
  shortId,
  statusInfo,
} from '../lib/format'

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const publicId = id ?? ''
  const [tab, setTab] = useState<'stream' | 'steps'>('stream')

  // Live task snapshot (polled + WS-patched from store).
  const taskQ = useAsync<TaskDetailT>(() => api.getTask(publicId), [publicId])
  const stepsQ = useAsync<TimelineResponse>(() => api.getTimeline(publicId), [publicId])
  const upsertTask = useAppStore((s) => s.upsertTask)
  const liveTask = useAppStore((s) => s.taskBriefs[publicId] ?? null)
  const taskEvents = useAppStore((s) => s.taskEvents[publicId] ?? [])
  const pushToast = useAppStore((s) => s.pushToast)

  useEffect(() => {
    if (taskQ.data) upsertTask(taskQ.data)
  }, [taskQ.data, upsertTask])

  // Subscribe to this task's WS topic while viewing.
  useEffect(() => {
    if (!publicId) return
    const ws = getWsClient()
    ws.subscribe(publicId)
    return () => ws.unsubscribe(publicId)
  }, [publicId])

  const active = isActiveStatus(liveTask?.status ?? taskQ.data?.status)
  useInterval(() => {
    if (active) {
      taskQ.reload()
      stepsQ.reload()
    }
  }, active ? 2500 : null)

  const task = liveTask ?? taskQ.data
  const steps = stepsQ.data?.steps ?? taskQ.data?.history ?? []

  const control = useTaskControls(publicId, () => {
    taskQ.reload()
    stepsQ.reload()
  }, pushToast)

  if (taskQ.error) {
    return (
      <div className="mx-auto max-w-5xl px-8 py-10">
        <ErrorBox message={taskQ.error} onRetry={taskQ.reload} />
      </div>
    )
  }
  if (taskQ.loading && !task) {
    return (
      <div className="mx-auto max-w-5xl px-8 py-10">
        <div className="panel">
          <LoadingSpinner label={`Loading task ${shortId(publicId)}`} />
        </div>
      </div>
    )
  }
  if (!task) {
    return (
      <div className="mx-auto max-w-5xl px-8 py-10">
        <div className="panel">
          <EmptyState icon="?" title="Task not found" hint={`No task with id ${publicId}`} />
        </div>
      </div>
    )
  }

  const info = statusInfo(task.status)
  const terminal = isTerminalStatus(task.status)
  const progress = task.progress

  return (
    <div className="mx-auto max-w-6xl px-8 py-8 page-enter">
      {/* breadcrumb + header */}
      <div className="flex items-center gap-2 text-[11px] text-ink-400">
        <Link to="/tasks" className="hover:text-ink-600">Tasks</Link>
        <span>/</span>
        <span className="text-ink-500">#{shortId(publicId)}</span>
      </div>

      <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusBadge status={task.status} pulse={active} size="md" />
            <span
              className={`rounded-full border px-2 py-px font-mono text-[9px] font-medium uppercase ${
                task.mode === 'plan'
                  ? 'text-violet-600 border-violet-500/30 bg-violet-500/8'
                  : 'text-sig-600 border-sig-500/30 bg-sig-50'
              }`}
            >
              {task.mode}
            </span>
            <span className="data-mono text-[11px] text-ink-400">{publicId}</span>
          </div>
          <h1 className="mt-3 font-display text-xl font-medium leading-snug text-ink-900">{task.request}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] text-ink-400">
            <span>created {fmtRelative(task.created_at)}</span>
            {task.started_at ? <span>started {fmtClock(task.started_at)}</span> : null}
            {task.finished_at ? <span>finished {fmtClock(task.finished_at)}</span> : null}
          </div>
        </div>

        {/* controls */}
        <div className="flex flex-wrap items-center gap-2">
          {active ? (
            <Button variant="warn" size="sm" onClick={control.pause} disabled={control.busy}>
              Pause
            </Button>
          ) : null}
          {(task.status === 'paused' || task.status === 'failed' || task.status === 'cancelled') ? (
            <Button variant="primary" size="sm" onClick={control.resume} disabled={control.busy}>
              Resume
            </Button>
          ) : null}
          {!terminal ? (
            <Button variant="danger" size="sm" onClick={control.cancel} disabled={control.busy}>
              Cancel
            </Button>
          ) : null}
          <Button variant="danger" size="sm" onClick={control.remove} disabled={control.busy}>
            Delete
          </Button>
        </div>
      </header>

      {/* summary stats */}
      <section className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <Stat label="Status" value={info.label} tone={info.tone === 'idle' ? 'default' : info.tone} />
        <Stat
          label="Progress"
          value={progress ? `${Math.round(progress.percent)}%` : '—'}
          tone={active ? 'active' : 'default'}
          sub={progress ? `${progress.completed_steps}/${progress.total_steps} steps` : undefined}
        />
        <Stat
          label="Tools"
          value={progress?.tool_count ?? 0}
          sub={progress?.current_step ? truncate(progress.current_step, 22) : undefined}
        />
        <Stat
          label="Retries"
          value={progress?.retry_count ?? 0}
          tone={(progress?.retry_count ?? 0) > 0 ? 'warn' : 'default'}
        />
        <Stat
          label="Steps failed"
          value={progress?.failed_steps ?? 0}
          tone={(progress?.failed_steps ?? 0) > 0 ? 'fail' : 'default'}
        />
        <Stat label="Duration" value={totalDuration(steps)} />
      </section>

      {/* progress bar */}
      <div className="panel mt-4 p-4">
        <ProgressMeter
          percent={progress?.percent ?? 0}
          completed={progress?.completed_steps}
          total={progress?.total_steps}
          failed={progress?.failed_steps}
          active={active}
        />
      </div>

      {/* result / error */}
      {task.result ? (
        <ResultBlock tone="ok" label="Result" text={task.result} />
      ) : null}
      {task.error ? (
        <ResultBlock tone="fail" label="Error" text={task.error} />
      ) : null}

      {/* tabs: live stream / execution steps */}
      <section className="panel mt-4 flex min-h-[20rem] flex-col p-5">
        <div className="mb-4 flex items-center gap-1 border-b border-ink-200/70 pb-2">
          <TabButton active={tab === 'stream'} onClick={() => setTab('stream')}>
            Live stream
            {active ? (
              <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-sig-500 animate-pulseDot" />
            ) : null}
          </TabButton>
          <TabButton active={tab === 'steps'} onClick={() => setTab('steps')}>
            Execution steps
            <span className="ml-1.5 data-mono text-[10px] text-ink-400">{steps.length}</span>
          </TabButton>
        </div>

        {tab === 'stream' ? (
          <div className="min-h-[16rem]">
            <LiveTimeline
              events={taskEvents}
              live={active}
              emptyHint={active ? 'Starting…' : 'No events captured'}
              maxHeight="22rem"
            />
          </div>
        ) : (
          <StepsTable steps={steps} loading={stepsQ.loading && steps.length === 0} />
        )}
      </section>
    </div>
  )
}

// ── Sub-components ──────────────────────────────────────────────────────

function ResultBlock({ tone, label, text }: { tone: 'ok' | 'fail'; label: string; text: string }) {
  const cls =
    tone === 'ok'
      ? 'border-ok-500/30 bg-ok-500/5'
      : 'border-bad-500/30 bg-bad-500/5'
  const labelCls = tone === 'ok' ? 'text-ok-600' : 'text-bad-600'
  return (
    <div className={`panel mt-4 p-5 ${cls}`}>
      <div className={`hud-label ${labelCls}`}>{label}</div>
      <pre className="mt-2.5 max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-ink-700">
        {text}
      </pre>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`focus-ring -mb-[9px] flex items-center border-b-2 px-3.5 py-2 text-xs font-medium transition-colors ${
        active
          ? 'border-sig-500 text-sig-700'
          : 'border-transparent text-ink-400 hover:text-ink-700'
      }`}
    >
      {children}
    </button>
  )
}

const STEP_TONE: Record<string, string> = {
  completed: 'text-ok-600',
  running: 'text-sig-600',
  failed: 'text-bad-600',
  pending: 'text-ink-500',
  skipped: 'text-ink-400',
}

const STEP_GLYPH: Record<string, string> = {
  completed: '✓',
  running: '▸',
  failed: '✕',
  pending: '·',
  skipped: '↦',
}

function StepsTable({ steps, loading }: { steps: ExecutionStep[]; loading: boolean }) {
  if (loading) return <LoadingSpinner label="Loading steps" />
  if (steps.length === 0) {
    return (
      <EmptyState
        icon="✦"
        title="No execution steps recorded"
        hint="Steps are written as I work through the task."
      />
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="hud-label border-b border-ink-200/70">
            <th className="py-2.5 pr-3 font-medium">#</th>
            <th className="py-2.5 pr-3 font-medium">Type</th>
            <th className="py-2.5 pr-3 font-medium">Name</th>
            <th className="py-2.5 pr-3 font-medium">Status</th>
            <th className="py-2.5 pr-3 text-right font-medium">Duration</th>
            <th className="py-2.5 pr-3 font-medium">Started</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={`${s.id ?? i}-${s.step_index}`} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-50/50">
              <td className="py-2.5 pr-3 data-mono text-ink-400">{s.step_index}</td>
              <td className="py-2.5 pr-3">
                <span className="rounded-md border border-ink-200 bg-ink-50 px-1.5 py-px font-mono text-[10px] text-ink-600">
                  {stepTypeLabel(s.step_type)}
                </span>
              </td>
              <td className="py-2.5 pr-3 font-mono text-ink-700">
                {s.name}
                {s.error ? (
                  <span className="mt-0.5 block truncate text-[10px] text-bad-600/80" title={s.error}>
                    {s.error}
                  </span>
                ) : null}
              </td>
              <td className={`py-2.5 pr-3 data-mono font-medium ${STEP_TONE[s.status] ?? 'text-ink-600'}`}>
                {STEP_GLYPH[s.status] ?? '·'} {s.status}
              </td>
              <td className="py-2.5 pr-3 text-right data-mono text-ink-500">{fmtMs(s.duration_ms)}</td>
              <td className="py-2.5 pr-3 data-mono text-ink-400">{fmtClock(s.started_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function stepTypeLabel(t: string): string {
  return t.replace(/_/g, ' ')
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function totalDuration(steps: ExecutionStep[]): string {
  const ms = steps.reduce((acc, s) => acc + (s.duration_ms || 0), 0)
  return fmtMs(ms)
}

// ── Task controls hook ──────────────────────────────────────────────────

type PushToast = ReturnType<typeof useAppStore.getState>['pushToast']

function useTaskControls(
  publicId: string,
  onChange: () => void,
  pushToast: PushToast,
) {
  const [busy, setBusy] = useState(false)
  const removeTaskStore = useAppStore((s) => s.removeTask)

  const run = async (fn: () => Promise<unknown>, okMsg: string, errMsg: string) => {
    setBusy(true)
    try {
      await fn()
      pushToast('ok', okMsg)
      onChange()
    } catch (e) {
      pushToast('fail', `${errMsg}: ${e instanceof ApiError ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  return {
    busy,
    pause: () => run(() => api.pauseTask(publicId), 'Task paused', 'Pause failed'),
    resume: () => run(() => api.resumeTask(publicId), 'Task resumed', 'Resume failed'),
    cancel: () => run(() => api.cancelTask(publicId), 'Task canceled', 'Cancel failed'),
    remove: () =>
      run(
        async () => {
          await api.deleteTask(publicId)
          removeTaskStore(publicId)
        },
        'Task deleted',
        'Delete failed',
      ),
  }
}
