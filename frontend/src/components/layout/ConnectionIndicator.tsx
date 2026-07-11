import { useAppStore } from '../../stores/appStore'

/** Live WebSocket connection indicator for the header. */
export function ConnectionIndicator() {
  const connected = useAppStore((s) => s.connected)
  return (
    <div className="flex items-center gap-2 rounded-md border border-ink-700/60 bg-ink-900/50 px-2.5 py-1">
      <span
        className={`h-2 w-2 rounded-full ${
          connected ? 'bg-ok-500 animate-pulseDot' : 'bg-bad-500'
        }`}
      />
      <span className="hud-label">
        {connected ? 'LIVE' : 'OFFLINE'}
      </span>
    </div>
  )
}
