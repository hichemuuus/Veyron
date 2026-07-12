import type { ReactNode } from 'react'

interface StatProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: ReactNode
  tone?: 'default' | 'ok' | 'warn' | 'fail' | 'active'
}

const TONE_TEXT: Record<NonNullable<StatProps['tone']>, string> = {
  default: 'text-ink-900',
  ok: 'text-ok-600',
  warn: 'text-warn-600',
  fail: 'text-bad-600',
  active: 'text-sig-600',
}

/**
 * Single metric cell used in dashboard + task detail summary strips.
 */
export function Stat({ label, value, sub, icon, tone = 'default' }: StatProps) {
  return (
    <div className="panel flex flex-col gap-2 p-4 transition-shadow hover:shadow-card-lg">
      <div className="flex items-center justify-between">
        <span className="hud-label">{label}</span>
        {icon ? <span className="text-ink-400">{icon}</span> : null}
      </div>
      <span className={`font-display text-3xl font-medium leading-none tracking-tight ${TONE_TEXT[tone]}`}>
        {value}
      </span>
      {sub ? <span className="text-[11px] text-ink-500">{sub}</span> : null}
    </div>
  )
}
