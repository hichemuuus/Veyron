import { useAppStore } from '../../stores/appStore'

const TONE: Record<string, string> = {
  info: 'border-sig-400/30 bg-ink-100 text-ink-700',
  ok: 'border-ok-500/30 bg-ok-500/8 text-ink-800',
  warn: 'border-warn-500/40 bg-warn-500/8 text-ink-800',
  fail: 'border-bad-500/40 bg-bad-500/8 text-ink-800',
}

const ICON: Record<string, string> = {
  info: '›',
  ok: '✓',
  warn: '!',
  fail: '✕',
}

const ICON_TONE: Record<string, string> = {
  info: 'text-sig-500',
  ok: 'text-ok-500',
  warn: 'text-warn-500',
  fail: 'text-bad-500',
}

/** Fixed-position stack of transient notifications. */
export function Toasts() {
  const toasts = useAppStore((s) => s.toasts)
  const dismiss = useAppStore((s) => s.dismissToast)
  if (toasts.length === 0) return null
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto animate-riseIn rounded-xl border bg-ink-100 px-3.5 py-2.5 text-xs shadow-card-lg ${TONE[t.tone]}`}
        >
          <div className="flex items-start gap-2.5">
            <span className={`mt-0.5 font-mono font-medium ${ICON_TONE[t.tone]}`}>
              {ICON[t.tone]}
            </span>
            <span className="text-wrap-safe flex-1 leading-relaxed">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="text-ink-400 transition-colors hover:text-ink-700"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
