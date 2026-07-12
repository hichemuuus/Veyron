import type { ReactNode } from 'react'

export function LoadingSpinner({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14 text-ink-400">
      <span className="relative flex h-7 w-7">
        <span className="absolute inset-0 rounded-full border-2 border-ink-200" />
        <span className="h-7 w-7 animate-spinSlow rounded-full border-2 border-transparent border-t-sig-500" />
      </span>
      <span className="hud-label">{label ?? 'Loading'}</span>
    </div>
  )
}

export function ErrorBox({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="panel border-bad-500/30 bg-bad-500/5 p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-bad-500/15 font-mono text-sm font-medium text-bad-600">
          !
        </span>
        <div className="min-w-0 flex-1">
          <div className="hud-label text-bad-600">Couldn't load this</div>
          <p className="mt-1.5 break-words font-mono text-xs text-bad-600/90">
            {message}
          </p>
        </div>
        {onRetry ? (
          <button
            onClick={onRetry}
            className="focus-ring shrink-0 rounded-lg border border-bad-500/40 bg-white px-2.5 py-1 text-[11px] font-medium text-bad-600 transition-colors hover:bg-bad-500/10"
          >
            Retry
          </button>
        ) : null}
      </div>
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
}: {
  title: string
  hint?: string
  icon?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon ? (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-ink-100 text-xl text-ink-400">
          {icon}
        </div>
      ) : null}
      <div className="font-display text-base font-medium text-ink-700">{title}</div>
      {hint ? <p className="max-w-sm text-sm leading-relaxed text-ink-500">{hint}</p> : null}
      {action}
    </div>
  )
}

/** Button used for primary actions across the app. */
export function Button({
  children,
  variant = 'default',
  size = 'md',
  className = '',
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'primary' | 'ghost' | 'danger' | 'warn'
  size?: 'sm' | 'md'
}) {
  const variants: Record<string, string> = {
    default:
      'border-ink-200 bg-white text-ink-700 hover:bg-ink-50 hover:border-ink-300 shadow-soft',
    primary:
      'border-sig-500 bg-sig-500 text-white hover:bg-sig-600 hover:border-sig-600 shadow-soft',
    ghost: 'border-transparent text-ink-500 hover:bg-ink-100 hover:text-ink-800',
    danger:
      'border-bad-500/40 bg-white text-bad-600 hover:bg-bad-500/10',
    warn: 'border-warn-500/40 bg-white text-warn-600 hover:bg-warn-500/10',
  }
  const sizes: Record<string, string> = {
    sm: 'px-2.5 py-1.5 text-[11px]',
    md: 'px-3.5 py-2 text-xs',
  }
  return (
    <button
      className={`focus-ring inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium transition-all active:scale-[0.97] ${variants[variant]} ${sizes[size]} ${className} disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100`}
      {...rest}
    >
      {children}
    </button>
  )
}
