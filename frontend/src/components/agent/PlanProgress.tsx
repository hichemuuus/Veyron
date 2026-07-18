import { useMemo } from 'react'
import type { WsEvent } from '../../api/types'
import {
  extractPlan,
  planPercent,
  STEP_STATUS_TONE,
  STEP_STATUS_GLYPH,
} from '../../lib/execution'
import { TONE_RING, TONE_DOT } from '../../lib/format'

const TONE_NODE: Record<string, string> = {
  ok: 'border-ok-500/40 bg-ok-500/10 text-ok-600',
  active: 'border-sig-500/40 bg-sig-500/10 text-sig-600',
  warn: 'border-warn-500/40 bg-warn-500/10 text-warn-600',
  fail: 'border-bad-500/40 bg-bad-500/10 text-bad-600',
  idle: 'border-ink-300 bg-ink-100 text-ink-500',
}

/**
 * Plan execution panel — shows the DAG-decomposed steps with verifier
 * status (completed / failed / error), retry count, and per-step tool calls.
 * Only renders when plan.* events have been emitted for this task.
 */
export function PlanProgress({ events }: { events: WsEvent[] }) {
  const plan = useMemo(() => extractPlan(events), [events])

  if (!plan.started) return null

  const pct = planPercent(plan)
  const activeStep = plan.steps.find((s) => s.status === 'running')

  return (
    <div className="rounded-xl border border-ink-200/70 bg-ink-100/50 p-3.5">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="hud-label text-violet-600">Plan</span>
          {plan.replanned > 0 ? (
            <span className="rounded-full border border-warn-500/40 bg-warn-500/10 px-1.5 py-px text-[9px] font-medium uppercase text-warn-600">
              ↻ replanned ×{plan.replanned}
            </span>
          ) : null}
          {plan.synthesized ? (
            <span className="rounded-full border border-ok-500/40 bg-ok-500/10 px-1.5 py-px text-[9px] font-medium uppercase text-ok-600">
              ✓ synthesized
            </span>
          ) : null}
        </div>
        <span className="data-mono text-[10px] text-ink-400">
          {plan.completed + plan.failed}/{plan.stepCount} steps
        </span>
      </div>

      {/* Plan progress bar */}
      <div className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-ink-200">
        <div
          className="h-full bg-gradient-to-r from-violet-500 to-sig-400 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Active step indicator */}
      {activeStep ? (
        <div className="mb-2.5 flex items-center gap-2 rounded-lg border border-sig-500/30 bg-sig-50 px-2.5 py-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-sig-500 animate-pulseDot" />
          <span className="hud-label">Now</span>
          <span className="truncate font-mono text-[11px] text-sig-700">{activeStep.goal}</span>
        </div>
      ) : null}

      {/* Step list */}
      <ol className="relative">
        <div className="absolute bottom-2 left-[11px] top-2 w-px bg-gradient-to-b from-violet-400/50 via-ink-200/60 to-transparent" />
        {plan.steps.map((step, i) => {
          const tone = STEP_STATUS_TONE[step.status]
          return (
            <li key={step.key} className={`relative pl-8 ${i === plan.steps.length - 1 ? 'pb-1' : 'pb-3'}`}>
              <div
                className={`absolute left-0 top-0.5 flex h-6 w-6 items-center justify-center rounded-lg border font-mono text-[11px] ${TONE_NODE[tone]}`}
              >
                {STEP_STATUS_GLYPH[step.status]}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-xs font-medium text-ink-800">{step.goal}</span>
                  {step.retry > 0 ? (
                    <span className="rounded-full border border-warn-500/30 bg-warn-500/10 px-1.5 py-px text-[9px] font-medium text-warn-600">
                      retry {step.retry}
                    </span>
                  ) : null}
                  <span
                    className={`rounded-full border px-1.5 py-px text-[9px] font-medium uppercase ${TONE_RING[tone]}`}
                  >
                    <span className={`mr-1 inline-block h-1 w-1 rounded-full ${TONE_DOT[tone]}`} />
                    {step.status}
                  </span>
                </div>
                {step.error ? (
                  <p className="mt-0.5 truncate font-mono text-[10px] text-bad-600/80" title={step.error}>
                    {step.error}
                  </p>
                ) : null}
                {step.toolCalls.length > 0 ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {step.toolCalls.map((tc, j) => (
                      <span
                        key={j}
                        className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-px font-mono text-[10px] ${
                          tc.ok
                            ? 'border-ok-500/30 text-ok-600 bg-ok-500/8'
                            : 'border-bad-500/30 text-bad-600 bg-bad-500/8'
                        }`}
                      >
                        ⚙ {tc.tool}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </li>
          )
        })}
      </ol>

      {plan.steps.length === 0 && plan.created ? (
        <p className="text-[11px] text-ink-400">
          {plan.stepCount} step(s) planned — waiting to begin.
        </p>
      ) : null}
    </div>
  )
}
