import { useMemo } from 'react'
import type { WsEvent } from '../../api/types'
import { eventMeta } from '../../api/types'
import { fmtClock } from '../../lib/format'

const TONE_NODE: Record<string, string> = {
  ok: 'border-ok-500/60 bg-ok-500/15 text-ok-400',
  active: 'border-sig-400/60 bg-sig-500/15 text-sig-300',
  warn: 'border-warn-500/60 bg-warn-500/15 text-warn-400',
  fail: 'border-bad-500/60 bg-bad-500/15 text-bad-400',
  info: 'border-ink-500/60 bg-ink-700/40 text-ink-300',
}

// Events that carry no user-facing action and would only add noise as a
// separate node. We aggregate agent.iteration counts separately.
const SUPPRESSED = new Set(['agent.iteration', 'agent.thinking'])

interface TimelineNode {
  ev: WsEvent
  meta: ReturnType<typeof eventMeta>
  key: string
}

interface LiveTimelineProps {
  events: WsEvent[]
  /** When true, show a pulsing "executing now" header. */
  live?: boolean
  emptyHint?: string
  maxHeight?: string
}

/**
 * Vertical, monospace execution timeline. Each WS event becomes a node with a
 * category-coded marker, timestamp, label, and a compact payload summary.
 *
 * No private chain-of-thought is shown: `agent.thinking` deltas are suppressed
 * (they are raw LLM stream fragments). `agent.iteration` counts are surfaced
 * as a header summary instead of individual nodes.
 */
export function LiveTimeline({
  events,
  live = false,
  emptyHint = 'Awaiting telemetry…',
  maxHeight = '100%',
}: LiveTimelineProps) {
  const { nodes, iterationCount, thinkingPulse } = useMemo(() => {
    let iterations = 0
    let pulse = false
    const seen: TimelineNode[] = []
    for (const ev of events) {
      if (ev.type === 'agent.iteration') {
        const it = Number((ev.payload as Record<string, unknown>).iteration ?? 0)
        if (it > iterations) iterations = it
        continue
      }
      if (ev.type === 'agent.thinking') {
        pulse = true
        continue
      }
      if (SUPPRESSED.has(ev.type)) continue
      seen.push({ ev, meta: eventMeta(ev.type), key: `${ev.ts}-${ev.type}-${seen.length}` })
    }
    // If the latest event is a terminal task.* one, stop the pulse.
    const lastType = events[events.length - 1]?.type
    if (lastType && ['task.completed', 'task.failed', 'task.cancelled'].includes(lastType)) {
      pulse = false
    }
    return { nodes: seen, iterationCount: iterations, thinkingPulse: pulse }
  }, [events])

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
        <div
          className={`h-2 w-2 rounded-full ${live ? 'bg-sig-400 animate-pulseDot' : 'bg-ink-600'}`}
        />
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-500">
          {emptyHint}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col" style={{ maxHeight }}>
      {(live || iterationCount > 0) && (
        <div className="mb-3 flex items-center justify-between rounded-md border border-ink-800/70 bg-ink-900/40 px-3 py-1.5">
          <div className="flex items-center gap-2">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                thinkingPulse ? 'bg-sig-400 animate-pulseDot' : 'bg-ink-600'
              }`}
            />
            <span className="hud-label">
              {thinkingPulse ? 'EXECUTING' : iterationCount > 0 ? 'IDLE' : 'STREAM'}
            </span>
          </div>
          {iterationCount > 0 ? (
            <span className="data-mono text-[11px] text-ink-300">
              {iterationCount} iter
            </span>
          ) : null}
        </div>
      )}

      <div className="relative overflow-y-auto pr-1" style={{ maxHeight }}>
        <ol className="relative">
          {/* spine */}
          <div className="absolute bottom-2 left-[11px] top-2 w-px bg-gradient-to-b from-ink-700/80 via-ink-700/40 to-transparent" />
          {nodes.map((n, i) => (
            <TimelineRow key={n.key} node={n} isLast={i === nodes.length - 1} />
          ))}
        </ol>
      </div>
    </div>
  )
}

function TimelineRow({ node, isLast }: { node: TimelineNode; isLast: boolean }) {
  const { ev, meta } = node
  const nodeCls = TONE_NODE[meta.tone]
  const summary = summarize(ev)

  return (
    <li className={`relative pl-8 ${isLast ? 'pb-1' : 'pb-4'}`}>
      <div
        className={`absolute left-0 top-0.5 flex h-6 w-6 items-center justify-center rounded-md border font-mono text-[11px] ${nodeCls}`}
      >
        {meta.glyph}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-200">{meta.label}</span>
          <span className="data-mono text-[10px] text-ink-500">
            {fmtClock(new Date(ev.ts * 1000).toISOString())}
          </span>
        </div>
        {summary ? (
          <p className="mt-0.5 truncate font-mono text-[11px] text-ink-400">{summary}</p>
        ) : null}
      </div>
    </li>
  )
}

/**
 * Extract a one-line, human-facing summary from the event payload.
 * Deliberately shows actions/tools/results — never reasoning text.
 */
function summarize(ev: WsEvent): string {
  const p = ev.payload as Record<string, unknown>
  switch (ev.type) {
    case 'task.intent': {
      const mode = p.mode as string
      const conf = Number(p.confidence ?? 0)
      return `mode=${mode} · confidence=${(conf * 100).toFixed(0)}%`
    }
    case 'plan.created': {
      const steps = p.steps as string[] | undefined
      return `${p.step_count ?? steps?.length ?? 0} steps planned`
    }
    case 'plan.step.start':
      return str(p.goal)
    case 'plan.step.complete':
      return `verified · ${str(p.goal)}`
    case 'plan.step.error':
      return `attempt ${p.attempt ?? '?'} · ${str(p.error)}`
    case 'plan.step.failed':
      return str(p.error ?? p.goal)
    case 'plan.step.tool': {
      const ok = p.ok ? 'ok' : 'fail'
      return `${str(p.tool)} (${ok})`
    }
    case 'plan.synthesized':
      return 'final result composed'
    case 'tool.request':
      return `${str(p.tool)}${p.iteration ? ` · iter ${p.iteration}` : ''}`
    case 'tool.result': {
      const ok = p.ok ? 'ok' : 'failed'
      const dur = p.duration_ms ? ` · ${fmtDur(Number(p.duration_ms))}` : ''
      return `${str(p.tool)} ${ok}${dur}`
    }
    case 'agent.answer':
      return truncate(str(p.answer), 80)
    case 'security.confirm':
      return `${str(p.tool)} · ${str(p.summary)}`
    case 'security.confirm.resolved':
      return p.approved ? 'approved' : 'denied'
    case 'task.failed':
      return str(p.error)
    default:
      return ''
  }
}

function str(v: unknown): string {
  if (v == null) return ''
  return String(v)
}
function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}
function fmtDur(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
