import { useEffect } from 'react'
import { getWsClient } from '../api/websocket'
import type { WsEvent } from '../api/types'
import { useAppStore, type Confirmation } from '../stores/appStore'

/**
 * Bootstraps the singleton WebSocket connection and routes server messages
 * into the global store: events into the log, confirmations into the pending
 * queue, and connection state for the connection indicator.
 *
 * Call once near the app root (Layout does this). Other components can attach
 * their own transient handlers via the `handler` argument.
 */
export function useWebSocket(handler?: (ev: WsEvent) => void) {
  const addEvent = useAppStore((s) => s.addEvent)
  const setConnected = useAppStore((s) => s.setConnected)
  const addConfirmation = useAppStore((s) => s.addConfirmation)
  const resolveConfirmation = useAppStore((s) => s.resolveConfirmation)

  useEffect(() => {
    const client = getWsClient()
    client.connect()

    const unsub = client.onEvent((msg) => {
      if (msg.type === 'ack' || msg.type === 'error') {
        // ack carries connection liveness implicitly; nothing to store.
        return
      }
      const ev = msg as WsEvent
      addEvent(ev)

      // Route confirmation lifecycle.
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
        if (conf.confirmation_id) addConfirmation(conf)
      } else if (ev.type === 'security.confirm.resolved') {
        const p = ev.payload as Record<string, unknown>
        const id = String(p.confirmation_id ?? '')
        if (id) resolveConfirmation(id)
      }

      handler?.(ev)
    })

    // Poll connection liveness a few times a second for the indicator.
    const id = window.setInterval(() => {
      setConnected(client.connected)
    }, 800)
    setConnected(client.connected)

    return () => {
      unsub()
      window.clearInterval(id)
    }
  }, [addEvent, setConnected, addConfirmation, resolveConfirmation, handler])
}
