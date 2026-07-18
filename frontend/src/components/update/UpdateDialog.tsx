import { useUpdateStore } from '../../stores/updateStore'
import { ProgressMeter } from '../ui/ProgressMeter'

interface UpdateDialogProps {
  open: boolean
  onClose: () => void
}

export function UpdateDialog({ open, onClose }: UpdateDialogProps) {
  const status = useUpdateStore((s) => s.status)
  const currentVersion = useUpdateStore((s) => s.currentVersion)
  const checkNow = useUpdateStore((s) => s.checkNow)
  const installUpdate = useUpdateStore((s) => s.installUpdate)
  const cancelDownload = useUpdateStore((s) => s.cancelDownload)
  const restartApp = useUpdateStore((s) => s.restartApp)

  if (!open) return null

  function renderContent() {
    switch (status.type) {
      case 'idle':
        return (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-ok-100">
              <svg className="h-7 w-7 text-ok-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="text-center">
              <h3 className="text-lg font-medium text-ink-900">Up to Date</h3>
              <p className="mt-1 text-sm text-ink-500">Veyron v{currentVersion} is the latest version.</p>
            </div>
            <button
              onClick={checkNow}
              className="focus-ring mt-2 rounded-lg bg-sig-500 px-5 py-2 text-sm font-medium text-white transition-all hover:bg-sig-600"
            >
              Check Again
            </button>
          </div>
        )

      case 'checking':
        return (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="relative flex h-14 w-14 items-center justify-center">
              <span className="absolute inset-0 rounded-full bg-sig-400/20 animate-breathe" />
              <span className="relative h-7 w-7 rounded-full border-2 border-sig-500 border-t-transparent animate-spin" />
            </div>
            <div className="text-center">
              <h3 className="text-lg font-medium text-ink-900">Checking for Updates...</h3>
              <p className="mt-1 text-sm text-ink-500">Looking for the latest version of Veyron.</p>
            </div>
          </div>
        )

      case 'available':
        return (
          <div className="flex flex-col gap-4 py-4">
            <div className="flex flex-col items-center gap-3">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-sky-100">
                <svg className="h-7 w-7 text-sky-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                </svg>
              </div>
              <div className="text-center">
                <h3 className="text-lg font-medium text-ink-900">Update Available</h3>
                <p className="mt-1 text-sm text-ink-500">Veyron v{status.version} is ready to install.</p>
              </div>
            </div>
            {status.body && (
              <div className="max-h-32 overflow-y-auto break-words rounded-lg bg-ink-100/60 p-3 text-xs text-ink-600">
                {status.body}
              </div>
            )}
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={onClose}
                className="focus-ring rounded-lg border border-ink-300 bg-ink-200 px-4 py-2 text-sm font-medium text-ink-800 transition-all hover:bg-ink-50"
              >
                Later
              </button>
              <button
                onClick={installUpdate}
                className="focus-ring rounded-lg bg-sig-500 px-5 py-2 text-sm font-medium text-white transition-all hover:bg-sig-600"
              >
                Update Now
              </button>
            </div>
          </div>
        )

      case 'downloading':
        return (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="relative flex h-14 w-14 items-center justify-center">
              <span className="absolute inset-0 rounded-full bg-sig-400/20 animate-breathe" />
              <span className="relative h-7 w-7 text-sig-500">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 5v14M5 12l7 7 7-7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            </div>
            <div className="w-full max-w-xs text-center">
              <h3 className="text-lg font-medium text-ink-900">Downloading Update</h3>
              <p className="mt-1 text-sm text-ink-500">v{status.version}</p>
              <div className="mt-4">
                <ProgressMeter
                  percent={Math.round(status.progress * 100)}
                  compact
                />
              </div>
              <p className="mt-2 text-xs text-ink-400">{Math.round(status.progress * 100)}%</p>
            </div>
            <button
              onClick={cancelDownload}
              className="focus-ring text-sm text-ink-500 underline hover:text-ink-700"
            >
              Cancel
            </button>
          </div>
        )

      case 'installing':
        return (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="relative flex h-14 w-14 items-center justify-center">
              <span className="absolute inset-0 rounded-full bg-amber-400/20 animate-breathe" />
              <span className="relative h-7 w-7 rounded-full border-2 border-amber-500 border-t-transparent animate-spin" />
            </div>
            <div className="text-center">
              <h3 className="text-lg font-medium text-ink-900">Installing...</h3>
              <p className="mt-1 text-sm text-ink-500">Please wait while the update is installed.</p>
            </div>
          </div>
        )

      case 'done':
        return (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-ok-100">
              <svg className="h-7 w-7 text-ok-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="text-center">
              <h3 className="text-lg font-medium text-ink-900">Update Complete</h3>
              <p className="mt-1 text-sm text-ink-500">Veyron has been updated. Restart to apply the changes.</p>
            </div>
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={onClose}
                className="focus-ring rounded-lg border border-ink-300 bg-ink-200 px-4 py-2 text-sm font-medium text-ink-800 transition-all hover:bg-ink-50"
              >
                Later
              </button>
              <button
                onClick={restartApp}
                className="focus-ring rounded-lg bg-sig-500 px-5 py-2 text-sm font-medium text-white transition-all hover:bg-sig-600"
              >
                Restart Now
              </button>
            </div>
          </div>
        )

      case 'failed':
        return (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
              <svg className="h-7 w-7 text-red-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
              </svg>
            </div>
            <div className="text-center">
              <h3 className="text-lg font-medium text-ink-900">Update Failed</h3>
              <p className="text-wrap-safe mt-2 max-w-xs text-sm text-ink-500">{status.error}</p>
            </div>
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={onClose}
                className="focus-ring rounded-lg border border-ink-300 bg-ink-200 px-4 py-2 text-sm font-medium text-ink-800 transition-all hover:bg-ink-50"
              >
                Close
              </button>
              <button
                onClick={checkNow}
                className="focus-ring rounded-lg bg-sig-500 px-5 py-2 text-sm font-medium text-white transition-all hover:bg-sig-600"
              >
                Retry
              </button>
            </div>
          </div>
        )
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl bg-ink-100 p-6 shadow-card border border-ink-200">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-base font-semibold text-ink-800">Software Update</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-ink-400 transition-all hover:bg-ink-100 hover:text-ink-600"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        {renderContent()}
      </div>
    </div>
  )
}
