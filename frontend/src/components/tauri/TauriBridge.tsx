import { useEffect, useRef } from 'react'
import { listen } from '@tauri-apps/api/event'
import { invoke } from '@tauri-apps/api/core'
import { useAppStore } from '../../stores/appStore'
import { useUpdateStore } from '../../stores/updateStore'

/** Drives the connection state machine from Tauri/Rust events. */
export function TauriBridge() {
  const cleanupRef = useRef<() => void>(() => {})
  const setupDoneRef = useRef(false)

  useEffect(() => {
    if (setupDoneRef.current) return
    setupDoneRef.current = true

    const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
    if (!isTauri) return

    const start = Date.now()
    const store = useAppStore.getState()
    store.setConnection({ state: 'starting' })
    store.setStartupStartedAt(start)

    let unlistenBackend: (() => void) | undefined
    let unlistenUpdate: (() => void) | undefined
    let unlistenCommand: (() => void) | undefined

    let cancelled = false

    async function setup() {
      unlistenBackend = await listen<string>('backend-status', (event) => {
        if (cancelled) return
        const s = useAppStore.getState()
        const status = event.payload
        if (status === 'starting') {
          s.setConnection({ state: 'starting_backend', reason: 'Backend process launching...' })
        } else if (status === 'running') {
          s.setBackendRunning(true)
        } else if (status === 'error') {
          s.setBackendRunning(false)
          s.setConnection({ state: 'error', reason: 'Backend process failed to start' })
        } else if (status === 'unhealthy') {
          s.setHealthOk(false)
        }
      })

      unlistenUpdate = await listen<string>('update-available', (event) => {
        if (cancelled) return
        console.log(`[Veyron Desktop] Update available: v${event.payload}`)
        // Trigger a check to populate the store
        useUpdateStore.getState().checkNow().catch(() => {})
      })

      unlistenCommand = await listen<string>('engine-command', (event) => {
        if (cancelled) return
        const cmd = event.payload
        if (cmd === 'restart') {
          console.log('[Veyron Desktop] Restarting AI engine...')
          window.location.reload()
        } else if (cmd === 'stop') {
          console.log('[Veyron Desktop] Stopping AI engine...')
          invoke('restart_backend').catch(() => {})
        } else if (cmd === 'check-for-updates') {
          console.log('[Veyron Desktop] Checking for updates from tray...')
          useUpdateStore.getState().checkNow().catch(() => {})
        }
      })

      try {
        const pid = await invoke<number | null>('get_backend_pid')
        if (pid != null && !cancelled) {
          useAppStore.getState().setBackendPid(pid)
        }
      } catch {
        // non-Tauri env or command not ready
      }
      try {
        await invoke<number>('get_backend_port')
      } catch {
        // ignore
      }

      // Fetch current version
      try {
        const ver = await invoke<string>('get_app_version')
        if (!cancelled) {
          useUpdateStore.getState().setCurrentVersion(ver)
        }
      } catch {
        // ignore
      }
    }

    setup()

    cleanupRef.current = () => {
      cancelled = true
      unlistenBackend?.()
      unlistenUpdate?.()
      unlistenCommand?.()
    }

    return () => {
      cleanupRef.current()
    }
  }, [])

  return null
}
