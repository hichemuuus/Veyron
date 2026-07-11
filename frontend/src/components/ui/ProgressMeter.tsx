import { fmtPct } from '../../lib/format'

interface ProgressMeterProps {
  percent: number | null | undefined
  completed?: number
  total?: number
  failed?: number
  active?: boolean
  compact?: boolean
}

/**
 * Horizontal progress meter with deterministic + indeterminate (scanning)
 * states. Used in task cards and the workspace.
 */
export function ProgressMeter({
  percent,
  completed,
  total,
  failed = 0,
  active = false,
  compact = false,
}: ProgressMeterProps) {
  const pct = Math.max(0, Math.min(100, percent ?? 0))
  const indeterminate = active && pct === 0
  const barColor = failed > 0 ? 'bg-warn-500' : active ? 'bg-sig-400' : 'bg-ok-500'

  return (
    <div className="w-full">
      <div
        className={`relative h-1.5 w-full overflow-hidden rounded-full bg-ink-700/70 ${
          indeterminate ? 'scanbar' : ''
        }`}
      >
        {!indeterminate && (
          <div
            className={`h-full rounded-full ${barColor} transition-all duration-500 ease-out`}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      {!compact && (
        <div className="mt-1 flex items-center justify-between text-[11px] text-ink-400 data-mono">
          <span>
            {completed != null && total != null ? `${completed}/${total} steps` : ''}
          </span>
          <span className={active ? 'text-sig-300' : ''}>
            {fmtPct(pct)}
            {failed > 0 ? ` · ${failed} failed` : ''}
          </span>
        </div>
      )}
    </div>
  )
}
