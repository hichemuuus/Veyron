import { useEffect, useRef } from 'react'
import { getWsClient, resetWsClient } from '../api/websocket'
import type { WsEvent } from '../api/types'
import { useAppStore, type Confirmation } from '../stores/appStore'

const handlerRef = { current: undefined as ((ev: WsEvent) => void) | undefined }

let _lastHealthCheckError = ''
export function getLastHealthCheckError(): string {
  return _lastHealthCheckError
}

const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
const baseUrl = isTauri ? 'http://127.0.0.1:8000' : ''

interface HttpResponse {
  status: number
  ok: boolean
  body: string
}

// Use custom Rust http_fetch command (reqwest) to bypass webview CORS/mixed-content.
// In browser dev, fall back to standard fetch (same-origin via Vite proxy).
let _invoke: ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | undefined
const tauriFetch = isTauri
  ? async (url: string, init?: RequestInit) => {
      if (!_invoke) {
        const m = await import('@tauri-apps/api/core')
        _invoke = m.invoke
      }
      const method = init?.method || 'GET'
      const headers = init?.headers ? Object.entries(init.headers as Record<string, string>) : undefined
      const body = init?.body as string | undefined
      const result = await _invoke('http_fetch', { url, method, headers, body }) as HttpResponse
      return new Response(result.body, { status: result.status, statusText: result.ok ? 'OK' : 'Error' })
    }
  : undefined

/**
 * Drives the full connection state machine:
 *   1. Wait for backend process (backendRunning = true)
 *   2. Poll health endpoint until 200 (abort if backend never starts)
 *   3. Verify REST API is reachable
 *   4. Connect WebSocket
 *
 * Connected = ALL conditions met. Any failure shows the state and reason.
 */
export function useWebSocket(handler?: (ev: WsEvent) => void) {
  handlerRef.current = handler
  const startedRef = useRef(false)

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true

    const healthUrl = `${baseUrl}/api/health`
    const restUrl = `${baseUrl}/api/info`

    let cancelled = false
    const intervals: ReturnType<typeof setInterval>[] = []
    let unsubHandler: (() => void) | null = null

    async function run() {
      const store = useAppStore.getState()
      store.setConnection({ state: 'starting' })

      // Wait for backendRunning with timeout
      // Also check for error state (Rust may have emitted "error" quickly)
      let backendStarted = false
      for (let i = 0; i < 60; i++) {
        if (cancelled) return
        const s = useAppStore.getState()
        if (s.backendRunning) { backendStarted = true; break }
        // If Rust reported an error, surface it immediately instead of waiting 30s
        if (s.connection.state === 'error') {
          store.setConnection({ state: 'error', reason: s.connection.reason || 'Backend process failed to start' })
          return
        }
        await new Promise((r) => setTimeout(r, 500))
      }
      if (cancelled) return
      if (!backendStarted) {
        store.setConnection({ state: 'error', reason: 'Backend process did not start within 30s timeout' })
        return
      }

      // Check health endpoint with retries
      store.setConnection({ state: 'waiting_health', reason: 'Waiting for health endpoint...' })
      let healthOk = false
      let lastHealthError = ''
      for (let i = 0; i < 30; i++) {
        if (cancelled) return
        try {
          const t0 = performance.now()
          const fet = tauriFetch ?? fetch
          const resp = await fet(healthUrl)
          _lastHealthCheckError = resp.ok ? '' : `HTTP ${resp.status}`
          store.setHealthLatency(Math.round(performance.now() - t0))
          if (resp.ok) { store.setHealthOk(true); healthOk = true; break }
          lastHealthError = `HTTP ${resp.status}`
        } catch (e) {
          lastHealthError = String(e)
          _lastHealthCheckError = String(e)
        }
        await new Promise((r) => setTimeout(r, 500))
      }
      if (cancelled) return
      if (!healthOk) {
        const detail = lastHealthError ? ` (${lastHealthError})` : ''
        store.setConnection({ state: 'error', reason: `Backend health endpoint not responding after 15s${detail}` })
        return
      }

      // Verify REST API
      store.setConnection({ state: 'connecting_ws', reason: 'Verifying REST API...' })
      let restOk = false
      for (let i = 0; i < 10; i++) {
        if (cancelled) return
        try {
          const t0 = performance.now()
          const fet = tauriFetch ?? fetch
          const resp = await fet(restUrl)
          store.setRestLatency(Math.round(performance.now() - t0))
          if (resp.ok) { store.setRestOk(true); restOk = true; break }
        } catch { /* REST not ready */ }
        await new Promise((r) => setTimeout(r, 300))
      }
      if (cancelled) return
      if (!restOk) {
        store.setConnection({ state: 'offline', reason: 'REST API unreachable after health check passed' })
        return
      }

      // Connect WebSocket
      store.setConnection({ state: 'connecting_ws', reason: 'Connecting WebSocket...' })
      const client = getWsClient()
      client.connect()
      for (let i = 0; i < 30; i++) {
        if (cancelled) return
        if (client.connected) { store.setWsConnected(true); break }
        await new Promise((r) => setTimeout(r, 200))
      }
      if (cancelled) return
      if (!client.connected) {
        store.setConnection({ state: 'offline', reason: 'WebSocket failed to connect' })
        return
      }

      store.setConnection({ state: 'connected' })

      unsubHandler = client.onEvent((msg) => {
        if (msg.type === 'ack' || msg.type === 'error') return
        const ev = msg as WsEvent
        store.addEvent(ev)
        if (ev.type === 'security.confirm') {
          const p = ev.payload as Record<string, unknown>
          const conf: Confirmation = {
            confirmation_id: String(p.confirmation_id ?? ''),
            topic: ev.topic ?? '',
            tool: String(p.tool ?? 'unknown'),
            permission: String(p.permission ?? 'CONFIRM'),
            summary: String(p.summary ?? ''),
            inputs: (p.inputs as Record<string, unknown>) ?? {},
          }
          if (conf.confirmation_id) store.addConfirmation(conf)
        } else if (ev.type === 'security.confirm.resolved') {
          const id = String((ev.payload as Record<string, unknown>).confirmation_id ?? '')
          if (id) store.resolveConfirmation(id)
        }
        handlerRef.current?.(ev)
      })

      const livenessPoll = setInterval(() => {
        useAppStore.getState().setWsConnected(client.connected)
      }, 2000)
      intervals.push(livenessPoll)

      const healthPoll = setInterval(async () => {
        try {
          const fet = tauriFetch ?? fetch
          const resp = await fet(healthUrl)
          _lastHealthCheckError = resp.ok ? '' : `HTTP ${resp.status}`
          useAppStore.getState().setHealthOk(resp.ok)
        } catch (e) {
          _lastHealthCheckError = String(e)
          useAppStore.getState().setHealthOk(false)
        }
      }, 15000)
      intervals.push(healthPoll)
    }

    run()

    return () => {
      cancelled = true
      intervals.forEach(clearInterval)
      unsubHandler?.()
      resetWsClient()
    }
  }, [])
}
