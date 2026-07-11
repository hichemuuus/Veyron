import type { ReactNode } from 'react'

interface StatProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: ReactNode
  tone?: 'default' | 'ok' | 'warn' | 'fail' | 'active'
}

const TONE_TEXT: Record<NonNullable<StatProps['tone']>, string> = {
  default: 'text-gray-100',
  ok: 'text-ok-400',
  warn: 'text-warn-400',
  fail: 'text-bad-400',
  active: 'text-sig-300',
}

/**
 * Single metric cell used in dashboard + task detail summary strips.
 */
export function Stat({ label, value, sub, icon, tone = 'default' }: StatProps) {
  return (
    <div className="panel flex flex-col gap-1 p-3">
      <div className="flex items-center justify-between">
        <span className="hud-label">{label}</span>
        {icon ? <span className="text-ink-400">{icon}</span> : null}
      </div>
      <span className={`data-mono text-2xl font-semibold leading-none ${TONE_TEXT[tone]}`}>
        {value}
      </span>
      {sub ? <span className="text-[11px] text-ink-400">{sub}</span> : null}
    </div>
  )
}
