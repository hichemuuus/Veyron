import { useAppStore } from '../../stores/appStore'

const TONE: Record<string, string> = {
  info: 'border-sig-400/40 bg-sig-500/10 text-sig-200',
  ok: 'border-ok-500/40 bg-ok-500/10 text-ok-400',
  warn: 'border-warn-500/40 bg-warn-500/10 text-warn-400',
  fail: 'border-bad-500/40 bg-bad-500/10 text-bad-400',
}

/** Fixed-position stack of transient notifications. */
export function Toasts() {
  const toasts = useAppStore((s) => s.toasts)
  const dismiss = useAppStore((s) => s.dismissToast)
  if (toasts.length === 0) return null
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto animate-riseIn rounded-lg border px-3 py-2 text-xs shadow-panel backdrop-blur ${TONE[t.tone]}`}
        >
          <div className="flex items-start gap-2">
            <span className="mt-0.5 font-mono">
              {t.tone === 'ok' ? '✓' : t.tone === 'fail' ? '✕' : t.tone === 'warn' ? '!' : '›'}
            </span>
            <span className="flex-1">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="text-current opacity-50 hover:opacity-100"
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
