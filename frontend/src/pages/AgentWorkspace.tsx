import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { TaskBrief } from '../api/types'
import { useAppStore } from '../stores/appStore'
import { getWsClient } from '../api/websocket'
import {
  StatusBadge,
  ProgressMeter,
  ErrorBox,
  EmptyState,
  Button,
} from '../components/ui'
import { LiveTimeline } from '../components/timeline/LiveTimeline'
import { fmtRelative, isActiveStatus, isTerminalStatus, shortId } from '../lib/format'

const EXAMPLE_GOALS = [
  'Audit my disk and memory usage and flag any concerns',
  'Read the project structure under the current directory',
  'Explain what processes are consuming the most CPU',
  'Plan and execute a review of system health, then summarize findings',
]

export function AgentWorkspacePage() {
  const [goal, setGoal] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const navigate = useNavigate()
  const pushToast = useAppStore((s) => s.pushToast)
  const upsertTask = useAppStore((s) => s.upsertTask)

  const activeTask = useAppStore((s) => (activeId ? s.taskBriefs[activeId] ?? null : null))
  const taskEvents = useAppStore((s) => (activeId ? s.taskEvents[activeId] ?? [] : []))

  // Subscribe to the active task's topic over WS for targeted delivery.
  useEffect(() => {
    if (!activeId) return
    const ws = getWsClient()
    ws.subscribe(activeId)
    return () => {
      ws.unsubscribe(activeId)
    }
  }, [activeId])

  const submit = async () => {
    const text = goal.trim()
    if (!text) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await api.createTask(text)
      const brief: TaskBrief = {
        public_id: res.public_id,
        request: text,
        status: 'created',
        mode: 'react',
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
        updated_at: new Date().toISOString(),
        progress: { total_steps: 0, completed_steps: 0, percent: 0 },
      }
      upsertTask(brief)
      setActiveId(res.public_id)
      pushToast('ok', `Mission dispatched · #${shortId(res.public_id)}`)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
      setError(msg)
      pushToast('fail', 'Failed to dispatch mission')
    } finally {
      setSubmitting(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-7xl flex-col px-6 py-6">
      <header className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-100">Agent Workspace</h1>
          <p className="mt-0.5 text-xs text-ink-400">
            Submit a mission. Observe planning, tool use, and verification in real time.
          </p>
        </div>
        <Link
          to="/tasks"
          className="focus-ring rounded-md border border-ink-700/60 px-3 py-1.5 text-xs text-ink-300 hover:bg-ink-800/60"
        >
          Task Registry →
        </Link>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Composer */}
        <section className="panel flex flex-col p-4 lg:col-span-2">
          <div className="mb-2 flex items-center gap-2">
            <span className="hud-label">Mission Directive</span>
          </div>
          <div className="relative flex-1">
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              onKeyDown={onKeyDown}
              rows={6}
              placeholder="Describe the outcome you want the agent to achieve…"
              className="focus-ring h-full min-h-[10rem] w-full resize-none rounded-lg border border-ink-700/70 bg-ink-900/70 p-3 text-sm text-gray-100 placeholder:text-ink-500"
            />
            <div className="pointer-events-none absolute bottom-2 right-3 font-mono text-[10px] text-ink-600">
              {goal.length}/8000 · ⌘↵ to dispatch
            </div>
          </div>

          {error ? (
            <div className="mt-3">
              <ErrorBox message={error} />
            </div>
          ) : null}

          <div className="mt-3 flex items-center justify-between gap-2">
            <span className="font-mono text-[10px] text-ink-500">
              {goal.trim() ? `${goal.trim().split(/\s+/).length} words` : 'ready'}
            </span>
            <Button
              variant="primary"
              onClick={submit}
              disabled={submitting || !goal.trim()}
            >
              {submitting ? 'Dispatching…' : 'Dispatch Mission →'}
            </Button>
          </div>

          <div className="mt-4 border-t border-ink-800/70 pt-3">
            <div className="hud-label mb-2">Example Directives</div>
            <div className="flex flex-col gap-1.5">
              {EXAMPLE_GOALS.map((g) => (
                <button
                  key={g}
                  onClick={() => setGoal(g)}
                  className="focus-ring rounded-md border border-transparent px-2.5 py-1.5 text-left text-xs text-ink-300 hover:border-ink-700/60 hover:bg-ink-850/60 hover:text-gray-200"
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Live execution */}
        <section className="panel flex min-h-0 flex-col p-4 lg:col-span-3">
          {activeTask ? (
            <ExecutionView task={activeTask} events={taskEvents} onOpenDetail={() => navigate(`/agent/${activeId}`)} />
          ) : (
            <EmptyState
              icon="▶"
              title="No active mission"
              hint="Dispatch a directive to watch the agent plan, act, and verify in real time."
            />
          )}
        </section>
      </div>
    </div>
  )
}

function ExecutionView({
  task,
  events,
  onOpenDetail,
}: {
  task: TaskBrief
  events: ReturnType<typeof useAppStore.getState>['events']
  onOpenDetail: () => void
}) {
  const active = isActiveStatus(task.status)
  const terminal = isTerminalStatus(task.status)
  const pct = task.progress?.percent ?? 0
  const hasResult = !!task.result
  const hasError = !!task.error

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* status header */}
      <div className="flex items-start justify-between gap-3 border-b border-ink-800/70 pb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="data-mono text-[10px] text-ink-500">#{shortId(task.public_id)}</span>
            <span
              className={`rounded border px-1 py-px font-mono text-[9px] uppercase ${
                task.mode === 'plan' ? 'text-violet-400 border-violet-500/30' : 'text-sig-400 border-sig-400/30'
              }`}
            >
              {task.mode}
            </span>
            <StatusBadge status={task.status} pulse={active} />
          </div>
          <p className="mt-1.5 truncate text-sm text-gray-200">{task.request}</p>
        </div>
        <button
          onClick={onOpenDetail}
          className="focus-ring shrink-0 rounded-md border border-ink-700/60 px-2.5 py-1 text-[11px] text-ink-300 hover:bg-ink-800/60"
        >
          Open detail →
        </button>
      </div>

      {/* progress */}
      <div className="border-b border-ink-800/70 py-3">
        <ProgressMeter
          percent={pct}
          completed={task.progress?.completed_steps}
          total={task.progress?.total_steps}
          failed={task.progress?.failed_steps}
          active={active}
        />
      </div>

      {/* result or error */}
      {hasResult || hasError ? (
        <div className="border-b border-ink-800/70 py-3">
          {hasError ? (
            <div className="rounded-lg border border-bad-500/30 bg-bad-500/5 p-3">
              <div className="hud-label text-bad-400">Execution Failed</div>
              <pre className="mt-1.5 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-bad-400/90">
                {task.error}
              </pre>
            </div>
          ) : (
            <div className="rounded-lg border border-ok-500/30 bg-ok-500/5 p-3">
              <div className="hud-label text-ok-400">Verified Result</div>
              <pre className="mt-1.5 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-ok-400/90">
                {task.result}
              </pre>
            </div>
          )}
        </div>
      ) : null}

      {/* timeline */}
      <div className="min-h-0 flex-1 overflow-hidden pt-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="hud-label">Execution Stream</span>
          {terminal ? (
            <span className="font-mono text-[10px] text-ink-500">
              finished {fmtRelative(task.finished_at ?? task.updated_at)}
            </span>
          ) : null}
        </div>
        <LiveTimeline events={events} live={active} emptyHint={active ? 'Establishing stream…' : 'Awaiting mission'} />
      </div>
    </div>
  )
}
