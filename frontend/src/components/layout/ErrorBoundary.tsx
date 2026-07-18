import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}
interface State {
  error: Error | null
}

/**
 * Top-level error boundary. Catches render errors anywhere in the tree so a
 * single faulty component doesn't white-screen the whole app. Renders a
 * recovery panel with a reset action.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
        console.error('Veyron render error:', error, info)
  }

  reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="flex h-screen items-center justify-center bg-ink-50 p-6">
        <div className="panel w-full max-w-md p-7">
          <div className="hud-label text-bad-600">Something went wrong</div>
          <h2 className="mt-2 font-display text-xl font-medium text-ink-900">
            The interface hit an unexpected error
          </h2>
          <pre className="mt-4 max-h-48 overflow-auto rounded-lg border border-ink-200 bg-ink-100 p-3 font-mono text-[11px] text-bad-600">
            {error.message}
          </pre>
          <div className="mt-5 flex justify-end gap-2">
            <button
              onClick={this.reset}
              className="focus-ring rounded-lg border border-sig-500/40 bg-sig-500/10 px-3.5 py-2 text-xs font-medium text-sig-700 hover:bg-sig-500/15"
            >
              Try again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="focus-ring rounded-lg border border-ink-200 bg-ink-100 px-3.5 py-2 text-xs font-medium text-ink-600 hover:bg-ink-200"
            >
              Reload
            </button>
          </div>
        </div>
      </div>
    )
  }
}
