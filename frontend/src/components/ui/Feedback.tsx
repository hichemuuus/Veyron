import type { ReactNode } from 'react'

export function LoadingSpinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-12 text-ink-400">
      <span className="h-4 w-4 animate-spinSlow rounded-full border-2 border-sig-400/40 border-t-sig-300" />
      <span className="font-mono text-xs uppercase tracking-[0.2em]">
        {label ?? 'Loading'}
      </span>
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
        <span className="mt-0.5 text-bad-400">⚠</span>
        <div className="min-w-0 flex-1">
          <div className="hud-label text-bad-400">Error</div>
          <p className="mt-1 break-words font-mono text-xs text-bad-400/90">
            {message}
          </p>
        </div>
        {onRetry ? (
          <button
            onClick={onRetry}
            className="focus-ring rounded border border-bad-500/40 px-2 py-1 text-[11px] text-bad-400 hover:bg-bad-500/10"
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
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon ? <div className="text-3xl text-ink-500">{icon}</div> : null}
      <div className="text-sm font-medium text-ink-300">{title}</div>
      {hint ? <p className="max-w-sm text-xs text-ink-400">{hint}</p> : null}
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
      'border-ink-600/70 bg-ink-750/70 text-gray-200 hover:bg-ink-700/70 hover:border-ink-500',
    primary:
      'border-sig-400/50 bg-sig-500/15 text-sig-200 hover:bg-sig-500/25 shadow-glow',
    ghost: 'border-transparent text-ink-300 hover:bg-ink-800/70 hover:text-gray-200',
    danger:
      'border-bad-500/40 bg-bad-500/10 text-bad-400 hover:bg-bad-500/20',
    warn: 'border-warn-500/40 bg-warn-500/10 text-warn-400 hover:bg-warn-500/20',
  }
  const sizes: Record<string, string> = {
    sm: 'px-2 py-1 text-[11px]',
    md: 'px-3 py-1.5 text-xs',
  }
  return (
    <button
      className={`focus-ring inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-colors ${variants[variant]} ${sizes[size]} ${className} disabled:cursor-not-allowed disabled:opacity-50`}
      {...rest}
    >
      {children}
    </button>
  )
}
