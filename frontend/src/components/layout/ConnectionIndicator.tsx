import { useAppStore } from '../../stores/appStore'

const STATUS_LOOKUP: Record<string, { border: string; bg: string; dot: string; label: string }> = {
  connected: {
    border: 'border-ok-500/30',
    bg: 'bg-ok-500/10',
    dot: 'bg-ok-500 animate-pulseDot',
    label: 'Connected',
  },
  starting_backend: {
    border: 'border-warn-500/30',
    bg: 'bg-warn-500/10',
    dot: 'bg-warn-500 animate-pulseDot',
    label: 'Starting backend',
  },
  waiting_health: {
    border: 'border-warn-500/30',
    bg: 'bg-warn-500/10',
    dot: 'bg-warn-500 animate-pulseDot',
    label: 'Waiting for backend',
  },
  connecting_ws: {
    border: 'border-warn-500/30',
    bg: 'bg-warn-500/10',
    dot: 'bg-warn-500 animate-pulseDot',
    label: 'Connecting',
  },
  offline: {
    border: 'border-bad-500/30',
    bg: 'bg-bad-500/10',
    dot: 'bg-bad-500',
    label: 'Offline',
  },
  error: {
    border: 'border-bad-500/30',
    bg: 'bg-bad-500/10',
    dot: 'bg-bad-500',
    label: 'Error',
  },
}

const DEFAULT = {
  border: 'border-ink-300/30',
  bg: 'bg-ink-300/10',
  dot: 'bg-ink-400',
  label: 'Starting',
}

/** Multi-axis connection indicator showing actual backend health. */
export function ConnectionIndicator() {
  const connection = useAppStore((s) => s.connection)
  const s = STATUS_LOOKUP[connection.state] ?? DEFAULT
  return (
    <div
      className={`flex items-center gap-2 rounded-full border px-2.5 py-1 transition-colors ${s.border} ${s.bg}`}
      title={connection.reason ?? ''}
    >
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      <span className="hud-label text-ink-600">{s.label}</span>
    </div>
  )
}
