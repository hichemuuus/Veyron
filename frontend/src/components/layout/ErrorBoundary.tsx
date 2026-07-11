import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}
interface State {
  error: Error | null
}

/**
 * Top-level error boundary. Catches render errors anywhere in the tree so a
 * single faulty component doesn't white-screen the whole cockpit. Renders a
 * recovery panel with a reset action.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('PAIOS render error:', error, info)
  }

  reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="flex h-screen items-center justify-center p-6">
        <div className="panel w-full max-w-md p-6">
          <div className="hud-label text-bad-400">RENDER FAULT</div>
          <h2 className="mt-2 text-base font-semibold text-gray-100">
            The interface hit an unexpected error
          </h2>
          <pre className="mt-3 max-h-48 overflow-auto rounded-md border border-ink-700/60 bg-ink-900/70 p-2 font-mono text-[11px] text-bad-400/90">
            {error.message}
          </pre>
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={this.reset}
              className="focus-ring rounded-md border border-sig-400/40 bg-sig-500/10 px-3 py-1.5 text-xs text-sig-200 hover:bg-sig-500/20"
            >
              Attempt Recovery
            </button>
            <button
              onClick={() => window.location.reload()}
              className="focus-ring rounded-md border border-ink-700/60 px-3 py-1.5 text-xs text-ink-300 hover:bg-ink-800/60"
            >
              Reload
            </button>
          </div>
        </div>
      </div>
    )
  }
}
