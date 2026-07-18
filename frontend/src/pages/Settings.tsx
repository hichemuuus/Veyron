import { useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { useUpdateStore, initUpdateListeners, cleanupUpdateListeners } from '../stores/updateStore'
import { UpdateDialog } from '../components/update/UpdateDialog'
import { api } from '../api/client'

export function SettingsPage() {
  const status = useUpdateStore((s) => s.status)
  const currentVersion = useUpdateStore((s) => s.currentVersion)
  const lastChecked = useUpdateStore((s) => s.lastChecked)
  const checkNow = useUpdateStore((s) => s.checkNow)
  const setCurrentVersion = useUpdateStore((s) => s.setCurrentVersion)

  const [backendVersion, setBackendVersion] = useState('')
  const [updateDialogOpen, setUpdateDialogOpen] = useState(false)
  const [config, setConfig] = useState<{
    auto_check: boolean
    channel: string
    last_check: string | null
  } | null>(null)

  useEffect(() => {
    initUpdateListeners()
    return () => cleanupUpdateListeners()
  }, [])

  useEffect(() => {
    const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
    if (!isTauri) return

    invoke<string>('get_app_version').then(setCurrentVersion).catch(() => {})
    invoke<{ updates: { auto_check: boolean; channel: string; last_check: string | null } }>('get_app_config')
      .then((cfg) => setConfig(cfg.updates))
      .catch(() => {})

    api.info().then((info) => setBackendVersion(info.version)).catch(() => {})
  }, [setCurrentVersion])

  function formatLastChecked(iso: string | null) {
    if (!iso) return 'Never'
    const d = new Date(iso)
    return d.toLocaleString()
  }

  function getStatusLabel() {
    switch (status.type) {
      case 'idle': return 'Up to date'
      case 'checking': return 'Checking...'
      case 'available': return `v${status.version} available`
      case 'downloading': return `Downloading v${status.version}...`
      case 'installing': return 'Installing...'
      case 'done': return 'Update ready'
      case 'failed': return 'Update failed'
    }
  }

  function getStatusTone() {
    switch (status.type) {
      case 'idle': return 'text-ok-600 bg-ok-50 border-ok-200'
      case 'checking':
      case 'downloading':
      case 'installing': return 'text-sky-600 bg-sky-50 border-sky-200'
      case 'available': return 'text-sig-600 bg-sig-50 border-sig-200'
      case 'done': return 'text-ok-600 bg-ok-50 border-ok-200'
      case 'failed': return 'text-red-600 bg-red-50 border-red-200'
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 px-6 py-8">
      <div>
        <h1 className="font-display text-xl font-semibold text-ink-800">Settings</h1>
        <p className="mt-1 text-sm text-ink-500">Application configuration and updates.</p>
      </div>

      {/* Update Section */}
      <section className="rounded-xl border border-ink-200/80 bg-ink-100 p-6">
        <h2 className="font-display text-base font-semibold text-ink-800">Software Updates</h2>

        <div className="mt-5 grid grid-cols-2 gap-4">
          <div>
            <span className="text-xs font-medium uppercase tracking-wider text-ink-400">Application Version</span>
            <p className="mt-1 font-mono text-sm text-ink-800">{currentVersion || '—'}</p>
          </div>
          <div>
            <span className="text-xs font-medium uppercase tracking-wider text-ink-400">Backend Version</span>
            <p className="mt-1 font-mono text-sm text-ink-800">{backendVersion || '—'}</p>
          </div>
          <div>
            <span className="text-xs font-medium uppercase tracking-wider text-ink-400">Last Checked</span>
            <p className="mt-1 font-mono text-sm text-ink-800">{lastChecked ? formatLastChecked(lastChecked) : (config?.last_check ? formatLastChecked(config.last_check) : 'Never')}</p>
          </div>
          <div>
            <span className="text-xs font-medium uppercase tracking-wider text-ink-400">Release Channel</span>
            <p className="mt-1 font-mono text-sm text-ink-800">{config?.channel ?? 'stable'}</p>
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between rounded-lg border border-ink-200/70 bg-ink-50/50 px-4 py-3">
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${getStatusTone()}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${status.type === 'checking' || status.type === 'downloading' || status.type === 'installing' ? 'animate-pulseDot bg-current' : 'bg-current'}`} />
              {getStatusLabel()}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => checkNow()}
              disabled={status.type === 'checking'}
              className="focus-ring rounded-lg border border-ink-300 bg-sig-500 px-3.5 py-1.5 text-sm font-medium text-ink-950 transition-all hover:bg-ink-50 disabled:opacity-50"
            >
              Check Now
            </button>
            {(status.type === 'available' || status.type === 'done') && (
              <button
                onClick={() => setUpdateDialogOpen(true)}
                className="focus-ring rounded-lg bg-sig-500 px-3.5 py-1.5 text-sm font-medium text-white transition-all hover:bg-sig-600"
              >
                {status.type === 'done' ? 'Restart' : 'Update'}
              </button>
            )}
          </div>
        </div>

        {status.type === 'available' && status.body && (
          <div className="mt-4">
            <span className="text-xs font-medium uppercase tracking-wider text-ink-400">Release Notes</span>
            <div className="mt-1.5 max-h-40 overflow-y-auto break-words rounded-lg bg-ink-50/80 p-3 text-xs text-ink-600">
              {status.body}
            </div>
          </div>
        )}
      </section>

      {/* About Section */}
      <section className="rounded-xl border border-ink-200/80 bg-ink-100 p-6">
        <h2 className="font-display text-base font-semibold text-ink-800">About</h2>
        <div className="mt-4 space-y-2 text-sm text-ink-600">
          <p>Veyron — AI Productivity System</p>
          <p>A local agent runtime that understands your system, remembers, plans, and acts under strict security controls.</p>
          <p className="pt-2 text-xs text-ink-400">
            Repository: <a href="https://github.com/hichemuuus/Veyron" target="_blank" rel="noopener noreferrer" className="text-wrap-safe text-sig-600 hover:underline">github.com/hichemuuus/Veyron</a>
          </p>
        </div>
      </section>

      <UpdateDialog open={updateDialogOpen} onClose={() => setUpdateDialogOpen(false)} />
    </div>
  )
}
