import { create } from 'zustand'
import type { SystemSnapshot, TaskBrief, WsEvent } from '../api/types'

/**
 * Richer connection state that reflects actual backend health.
 *
 * Connection is only "connected" when ALL conditions are true:
 *   1. Backend process is running (Rust signal)
 *   2. Health endpoint returns HTTP 200
 *   3. REST API is reachable
 *   4. WebSocket is connected
 */
export type ConnectionStatus =
  | { state: 'starting'; reason?: string }
  | { state: 'starting_backend'; reason?: string }
  | { state: 'waiting_health'; reason?: string }
  | { state: 'connecting_ws'; reason?: string }
  | { state: 'connected'; reason?: string }
  | { state: 'offline'; reason: string }
  | { state: 'error'; reason: string }

export interface Confirmation {
  confirmation_id: string
  topic: string
  tool: string
  permission: string
  summary: string
  inputs: Record<string, unknown>
}

export interface Toast {
  id: string
  tone: 'info' | 'ok' | 'warn' | 'fail'
  message: string
}

interface AppState {
  /** Multi-axis connection state — Connected only when ALL subsystems pass. */
  connection: ConnectionStatus
  setConnection: (v: ConnectionStatus) => void

  /** true when the backend process reports "running" from Rust */
  backendRunning: boolean
  setBackendRunning: (v: boolean) => void

  /** true when /api/health responds 200 */
  healthOk: boolean
  setHealthOk: (v: boolean) => void

  /** true when any REST endpoint succeeds */
  restOk: boolean
  setRestOk: (v: boolean) => void

  /** true when WebSocket readyState is OPEN */
  wsConnected: boolean
  setWsConnected: (v: boolean) => void

  /** Last health check latency in ms */
  healthLatency: number | null
  setHealthLatency: (v: number | null) => void

  /** Last REST check latency in ms */
  restLatency: number | null
  setRestLatency: (v: number | null) => void

  /** Backend PID (from Rust) */
  backendPid: number | null
  setBackendPid: (v: number | null) => void

  /** Overall startup duration tracking */
  startupStartedAt: number | null
  setStartupStartedAt: (v: number | null) => void

  // events (global)
  events: WsEvent[]
  addEvent: (ev: WsEvent) => void
  clearEventLog: () => void

  // per-task event logs (for task detail + workspace)
  taskEvents: Record<string, WsEvent[]>
  taskBriefs: Record<string, TaskBrief>

  upsertTask: (t: TaskBrief) => void
  upsertTasks: (ts: TaskBrief[]) => void
  removeTask: (publicId: string) => void

  // confirmations
  confirmations: Confirmation[]
  addConfirmation: (c: Confirmation) => void
  resolveConfirmation: (id: string) => void

  // toasts
  toasts: Toast[]
  pushToast: (tone: Toast['tone'], message: string) => void
  dismissToast: (id: string) => void

  // system monitoring snapshot (pushed via WebSocket)
  systemSnapshot: SystemSnapshot | null
  setSystemSnapshot: (snap: SystemSnapshot) => void
}

const MAX_EVENTS = 400
const MAX_TASK_EVENTS = 300

function computeConnection(flags: {
  backendRunning: boolean
  healthOk: boolean
  restOk: boolean
  wsConnected: boolean
  healthLatency: number | null
  restLatency: number | null
}): ConnectionStatus {
  if (!flags.backendRunning) return { state: 'starting_backend', reason: 'Backend process not yet started' }
  if (!flags.healthOk) return { state: 'waiting_health', reason: 'Health endpoint not responding' }
  if (!flags.restOk) return { state: 'offline', reason: 'REST API unreachable' }
  if (!flags.wsConnected) return { state: 'connecting_ws', reason: 'WebSocket not connected' }
  return { state: 'connected' }
}

export const useAppStore = create<AppState>((set, get) => ({
  connection: { state: 'starting' },
  setConnection: (v) => set({ connection: v }),

  backendRunning: false,
  setBackendRunning: (v) => {
    set({ backendRunning: v })
    const s = get()
    set({ connection: computeConnection({ backendRunning: v, healthOk: s.healthOk, restOk: s.restOk, wsConnected: s.wsConnected, healthLatency: s.healthLatency, restLatency: s.restLatency }) })
  },

  healthOk: false,
  setHealthOk: (v) => {
    set({ healthOk: v })
    const s = get()
    set({ connection: computeConnection({ backendRunning: s.backendRunning, healthOk: v, restOk: s.restOk, wsConnected: s.wsConnected, healthLatency: s.healthLatency, restLatency: s.restLatency }) })
  },

  restOk: false,
  setRestOk: (v) => {
    set({ restOk: v })
    const s = get()
    set({ connection: computeConnection({ backendRunning: s.backendRunning, healthOk: s.healthOk, restOk: v, wsConnected: s.wsConnected, healthLatency: s.healthLatency, restLatency: s.restLatency }) })
  },

  wsConnected: false,
  setWsConnected: (v) => {
    set({ wsConnected: v })
    const s = get()
    set({ connection: computeConnection({ backendRunning: s.backendRunning, healthOk: s.healthOk, restOk: s.restOk, wsConnected: v, healthLatency: s.healthLatency, restLatency: s.restLatency }) })
  },

  healthLatency: null,
  setHealthLatency: (v) => set({ healthLatency: v }),

  restLatency: null,
  setRestLatency: (v) => set({ restLatency: v }),

  backendPid: null,
  setBackendPid: (v) => set({ backendPid: v }),

  startupStartedAt: null,
  setStartupStartedAt: (v) => set({ startupStartedAt: v }),

  events: [],
  addEvent: (ev) =>
    set((s) => {
      const events = [...s.events.slice(-(MAX_EVENTS - 1)), ev]
      const topic = ev.topic ?? ''
      const taskEvents = { ...s.taskEvents }
      if (topic) {
        const prev = taskEvents[topic] ?? []
        taskEvents[topic] = [...prev.slice(-(MAX_TASK_EVENTS - 1)), ev]
      }
      const briefs = { ...s.taskBriefs }
      const existing = topic ? briefs[topic] : undefined
      if (topic && existing) {
        const p = ev.payload as Record<string, unknown>
        let next: TaskBrief | undefined
        switch (ev.type) {
          case 'task.completed':
            next = { ...existing, status: 'completed', updated_at: new Date().toISOString() }
            break
          case 'task.failed':
            next = {
              ...existing,
              status: 'failed',
              error: (p.error as string) ?? existing.error,
              updated_at: new Date().toISOString(),
            }
            break
          case 'task.paused':
            next = { ...existing, status: 'paused' }
            break
          case 'task.cancelled':
            next = { ...existing, status: 'cancelled' }
            break
          case 'task.started':
            next = { ...existing, status: 'running', started_at: new Date().toISOString() }
            break
          case 'plan.start':
            next = { ...existing, status: 'planning', mode: 'plan' }
            break
          default:
            break
        }
        if (next) briefs[topic] = next
      }
      return { events, taskEvents, taskBriefs: briefs }
    }),
  clearEventLog: () => set({ events: [] }),

  taskEvents: {},
  taskBriefs: {},

  upsertTask: (t) =>
    set((s) => ({ taskBriefs: { ...s.taskBriefs, [t.public_id]: t } })),
  upsertTasks: (ts) =>
    set((s) => {
      const next = { ...s.taskBriefs }
      for (const t of ts) next[t.public_id] = t
      return { taskBriefs: next }
    }),
  removeTask: (publicId) =>
    set((s) => {
      const briefs = { ...s.taskBriefs }
      delete briefs[publicId]
      const taskEvents = { ...s.taskEvents }
      delete taskEvents[publicId]
      return { taskBriefs: briefs, taskEvents }
    }),

  confirmations: [],
  addConfirmation: (c) =>
    set((s) =>
      s.confirmations.some((x) => x.confirmation_id === c.confirmation_id)
        ? s
        : { confirmations: [...s.confirmations, c] },
    ),
  resolveConfirmation: (id) =>
    set((s) => ({ confirmations: s.confirmations.filter((c) => c.confirmation_id !== id) })),

  toasts: [],
  pushToast: (tone, message) => {
    const id = Math.random().toString(36).slice(2)
    set((s) => ({ toasts: [...s.toasts, { id, tone, message }] }))
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 4200)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  systemSnapshot: null,
  setSystemSnapshot: (snap) => set({ systemSnapshot: snap }),
}))
