import { create } from 'zustand'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

export type UpdateStatus =
  | { type: 'idle' }
  | { type: 'checking' }
  | { type: 'available'; version: string; date: string; body: string; downloadUrl: string }
  | { type: 'downloading'; version: string; progress: number }
  | { type: 'installing' }
  | { type: 'done' }
  | { type: 'failed'; error: string }

interface UpdateStore {
  status: UpdateStatus
  currentVersion: string
  lastChecked: string | null
  listenersInitialized: boolean

  checkNow: () => Promise<void>
  installUpdate: () => Promise<void>
  cancelDownload: () => Promise<void>
  restartApp: () => Promise<void>
  setStatus: (status: UpdateStatus) => void
  setCurrentVersion: (v: string) => void
}

let unlistenStatus: (() => void) | undefined
let unlistenProgress: (() => void) | undefined
let unlistenAvailable: (() => void) | undefined

export const useUpdateStore = create<UpdateStore>((set, get) => ({
  status: { type: 'idle' },
  currentVersion: '',
  lastChecked: null,
  listenersInitialized: false,

  checkNow: async () => {
    set({ status: { type: 'checking' } })
    try {
      const info = await invoke<{ version: string; date: string; body: string; download_url: string } | null>('check_update')
      if (info) {
        set({
          status: {
            type: 'available',
            version: info.version,
            date: info.date,
            body: info.body,
            downloadUrl: info.download_url,
          },
          lastChecked: new Date().toISOString(),
        })
      } else {
        set({ status: { type: 'idle' }, lastChecked: new Date().toISOString() })
      }
    } catch (e) {
      set({ status: { type: 'failed', error: String(e) } })
    }
  },

  installUpdate: async () => {
    const s = get().status
    if (s.type !== 'available') return
    set({ status: { type: 'downloading', version: s.version, progress: 0 } })
    try {
      await invoke('install_update')
      set({ status: { type: 'done' } })
    } catch (e) {
      set({ status: { type: 'failed', error: String(e) } })
    }
  },

  cancelDownload: async () => {
    try {
      await invoke('cancel_download')
      set({ status: { type: 'idle' } })
    } catch {
      // ignore if no active download
    }
  },

  restartApp: async () => {
    try {
      await invoke('restart_app')
    } catch {
      window.location.reload()
    }
  },

  setStatus: (status) => set({ status }),
  setCurrentVersion: (v) => set({ currentVersion: v }),
}))

/** Initialize update event listeners. Safe to call multiple times — cleans up first. */
export async function initUpdateListeners() {
  const store = useUpdateStore
  if (store.getState().listenersInitialized) return

  unlistenStatus?.()
  unlistenProgress?.()
  unlistenAvailable?.()

  unlistenStatus = await listen<string>('update:status-changed', (event) => {
    const payload = event.payload
    switch (payload) {
      case 'checking':
        store.getState().setStatus({ type: 'checking' })
        break
      case 'available':
        break
      case 'idle':
        store.getState().setStatus({ type: 'idle' })
        break
      case 'downloading':
        break
      case 'installing': {
        const s = store.getState().status
        if (s.type === 'downloading') {
          store.getState().setStatus({ type: 'installing' })
        }
        break
      }
      case 'done':
        store.getState().setStatus({ type: 'done' })
        break
      case 'failed':
        break
    }
  })

  unlistenProgress = await listen<number>('update:download-progress', (event) => {
    const s = store.getState().status
    if (s.type === 'downloading') {
      store.getState().setStatus({
        type: 'downloading',
        version: s.version,
        progress: event.payload,
      })
    }
  })

  unlistenAvailable = await listen<string>('update-available', () => {
    // The frontend can check when user navigates to settings
  })

  store.getState().listenersInitialized = true
}

export function cleanupUpdateListeners() {
  unlistenStatus?.()
  unlistenStatus = undefined
  unlistenProgress?.()
  unlistenProgress = undefined
  unlistenAvailable?.()
  unlistenAvailable = undefined
  useUpdateStore.getState().listenersInitialized = false
}
