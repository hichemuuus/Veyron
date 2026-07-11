import { TONE_RING, TONE_DOT, statusInfo, type StatusTone } from '../../lib/format'

interface StatusBadgeProps {
  status?: string | null
  label?: string
  tone?: StatusTone
  pulse?: boolean
  size?: 'sm' | 'md'
}

/**
 * Compact status pill. Pass either a raw `status` (classified) or an explicit
 * tone+label override.
 */
export function StatusBadge({
  status,
  label,
  tone,
  pulse,
  size = 'sm',
}: StatusBadgeProps) {
  const info = tone
    ? { tone, label: label ?? status ?? '' }
    : statusInfo(status)
  const ring = TONE_RING[info.tone]
  const dot = TONE_DOT[info.tone]
  const pad = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${ring} ${pad}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${dot} ${
          (pulse ?? info.tone === 'active') ? 'animate-pulseDot' : ''
        }`}
      />
      {info.label}
    </span>
  )
}
