import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { TaskBrief, WsEvent } from '../api/types'
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
import { ToolCallCard } from '../components/agent/ToolCallCard'
import { PlanProgress } from '../components/agent/PlanProgress'
import { MemoryIndicator } from '../components/agent/MemoryIndicator'
import { extractToolCalls } from '../lib/execution'
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
      pushToast('ok', `Task started · #${shortId(res.public_id)}`)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
      setError(msg)
      pushToast('fail', 'Could not start that task')
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
    <div className="mx-auto flex h-full max-w-6xl flex-col px-8 py-8 page-enter">
      <header className="mb-5 flex items-end justify-between">
        <div>
          <h1 className="font-display text-display-sm font-medium text-ink-900">Agent</h1>
          <p className="mt-1 text-sm text-ink-500">
            Describe what you want done. I'll plan, act, and verify each step.
          </p>
        </div>
        <Link
          to="/tasks"
          className="focus-ring rounded-lg border border-ink-200 bg-ink-100 px-3.5 py-2 text-xs font-medium text-ink-400 transition-colors hover:bg-ink-200"
        >
          All tasks →
        </Link>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 lg:grid-cols-5">
        {/* Composer */}
        <section className="panel flex flex-col p-5 lg:col-span-2">
          <div className="mb-3">
            <span className="hud-label">Your goal</span>
          </div>
          <div className="relative flex-1">
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              onKeyDown={onKeyDown}
              rows={6}
              placeholder="What would you like me to do?"
              className="focus-ring h-full min-h-[10rem] w-full resize-none rounded-xl border border-ink-200 bg-ink-100/50 p-3.5 text-sm leading-relaxed text-ink-900 placeholder:text-ink-400"
            />
            <div className="pointer-events-none absolute bottom-2.5 right-3.5 font-mono text-[10px] text-ink-400">
              {goal.length}/8000 · ⌘↵ to run
            </div>
          </div>

          {error ? (
            <div className="mt-3">
              <ErrorBox message={error} />
            </div>
          ) : null}

          <div className="mt-4 flex items-center justify-between gap-2">
            <span className="font-mono text-[10px] text-ink-400">
              {goal.trim() ? `${goal.trim().split(/\s+/).length} words` : 'ready'}
            </span>
            <Button
              variant="primary"
              onClick={submit}
              disabled={submitting || !goal.trim()}
            >
              {submitting ? 'Starting…' : 'Run →'}
            </Button>
          </div>

          <div className="mt-5 border-t border-ink-200/70 pt-4">
            <div className="hud-label mb-2.5">Try one of these</div>
            <div className="flex flex-col gap-1.5">
              {EXAMPLE_GOALS.map((g) => (
                <button
                  key={g}
                  onClick={() => setGoal(g)}
                  className="focus-ring rounded-lg border border-transparent px-3 py-2 text-left text-xs leading-relaxed text-ink-500 transition-colors hover:border-ink-200 hover:bg-ink-100 hover:text-ink-800"
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Live execution */}
        <section className="panel flex min-h-0 flex-col p-5 lg:col-span-3">
          {activeTask ? (
            <ExecutionView task={activeTask} events={taskEvents} onOpenDetail={() => navigate(`/agent/${activeId}`)} />
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <EmptyState
                icon="✦"
                title="Nothing running yet"
                hint="Write a goal and run it. I'll think it through, use tools, and verify the result — you'll see it all here in real time."
              />
            </div>
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
  events: WsEvent[]
  onOpenDetail: () => void
}) {
  const active = isActiveStatus(task.status)
  const terminal = isTerminalStatus(task.status)
  const pct = task.progress?.percent ?? 0
  const hasResult = !!task.result
  const hasError = !!task.error

  const toolCalls = useMemo(() => extractToolCalls(events), [events])
  const hasPlanEvents = useMemo(
    () => events.some((e) => e.type.startsWith('plan.')),
    [events],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* status header */}
      <div className="flex items-start justify-between gap-3 border-b border-ink-200/70 pb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="data-mono text-[10px] text-ink-400">#{shortId(task.public_id)}</span>
            <span
              className={`rounded-full border px-2 py-px font-mono text-[9px] uppercase font-medium ${
                task.mode === 'plan' ? 'text-violet-600 border-violet-500/30 bg-violet-500/8' : 'text-sig-600 border-sig-500/30 bg-sig-50'
              }`}
            >
              {task.mode}
            </span>
            <StatusBadge status={task.status} pulse={active} />
          </div>
          <p className="mt-2 truncate text-sm text-ink-800">{task.request}</p>
        </div>
        <div className="min-w-0 shrink-0">
          <div className="flex items-center gap-2">
            <div className="overflow-hidden">
              <MemoryIndicator active={active} />
            </div>
            <button
              onClick={onOpenDetail}
              className="focus-ring shrink-0 rounded-lg border border-ink-200 bg-ink-100 px-2.5 py-1.5 text-[11px] font-medium text-ink-400 transition-colors hover:bg-ink-200"
            >
              Details →
            </button>
          </div>
        </div>
      </div>

      {/* progress */}
      <div className="border-b border-ink-200/70 py-4">
        <ProgressMeter
          percent={pct}
          completed={task.progress?.completed_steps}
          total={task.progress?.total_steps}
          failed={task.progress?.failed_steps}
          active={active}
        />
      </div>

      {/* Plan execution panel (only when plan events exist) */}
      {hasPlanEvents ? (
        <div className="border-b border-ink-200/70 py-4">
          <PlanProgress events={events} />
        </div>
      ) : null}

      {/* Tool execution cards */}
      {toolCalls.length > 0 ? (
        <div className="border-b border-ink-200/70 py-4">
          <div className="mb-2.5 flex items-center justify-between">
            <span className="hud-label">Tools used</span>
            <span className="data-mono text-[10px] text-ink-400">
              {toolCalls.length} call{toolCalls.length === 1 ? '' : 's'} ·{' '}
              {toolCalls.filter((c) => c.result?.ok).length} ok ·{' '}
              {toolCalls.filter((c) => c.result && !c.result.ok).length} failed
            </span>
          </div>
          <div className="flex max-h-64 flex-col gap-2 overflow-y-auto pr-1">
            {toolCalls.map((c) => (
              <ToolCallCard key={c.key} call={c} />
            ))}
          </div>
        </div>
      ) : null}

      {/* result or error */}
      {hasResult || hasError ? (
        <div className="border-b border-ink-200/70 py-4">
          {hasError ? (
            <div className="rounded-xl border border-bad-500/30 bg-bad-500/5 p-3.5">
              <div className="hud-label text-bad-600">Couldn't complete</div>
              <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-bad-600/90">
                {task.error}
              </pre>
            </div>
          ) : (
            <div className="rounded-xl border border-ok-500/30 bg-ok-500/5 p-3.5">
              <div className="hud-label text-ok-600">Result</div>
              <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-ink-700">
                {task.result}
              </pre>
            </div>
          )}
        </div>
      ) : null}

      {/* timeline */}
      <div className="min-h-0 flex-1 overflow-hidden pt-4">
        <div className="mb-2.5 flex items-center justify-between">
          <span className="hud-label">Activity</span>
          {terminal ? (
            <span className="font-mono text-[10px] text-ink-400">
              finished {fmtRelative(task.finished_at ?? task.updated_at)}
            </span>
          ) : null}
        </div>
        <LiveTimeline events={events} live={active} emptyHint={active ? 'Starting…' : 'Waiting to begin'} />
      </div>
    </div>
  )
}
