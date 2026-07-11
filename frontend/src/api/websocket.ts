import type { WsClientMessage, WsServerMessage } from './types'

export type EventHandler = (msg: WsServerMessage) => void

export class WebSocketClient {
  private ws: WebSocket | null = null
  private handlers = new Set<EventHandler>()
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private shouldReconnect = true
  private url: string

  constructor(url?: string) {
    this.url = url || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return
    this.shouldReconnect = true

    try {
      this.ws = new WebSocket(this.url)
    } catch (err) {
      console.error('WebSocket connection failed:', err)
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      console.log('WebSocket connected')
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: WsServerMessage = JSON.parse(event.data)
        this.handlers.forEach((h) => h(msg))
      } catch (err) {
        console.warn('WebSocket parse error:', err)
      }
    }

    this.ws.onclose = () => {
      console.log('WebSocket disconnected')
      if (this.shouldReconnect) {
        this.scheduleReconnect()
      }
    }

    this.ws.onerror = (err) => {
      console.error('WebSocket error:', err)
    }
  }

  disconnect(): void {
    this.shouldReconnect = false
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }

  send(msg: WsClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    } else {
      console.warn('WebSocket not open, cannot send')
    }
  }

  subscribe(topic: string): void {
    this.send({ type: 'subscribe', topic })
  }

  unsubscribe(topic: string): void {
    this.send({ type: 'unsubscribe', topic })
  }

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler)
    return () => {
      this.handlers.delete(handler)
    }
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (this.shouldReconnect) {
        console.log('WebSocket reconnecting...')
        this.connect()
      }
    }, 3000)
  }
}

let _wsClient: WebSocketClient | null = null

export function getWsClient(): WebSocketClient {
  if (!_wsClient) {
    _wsClient = new WebSocketClient()
  }
  return _wsClient
}

export function resetWsClient(): void {
  _wsClient?.disconnect()
  _wsClient = null
}
