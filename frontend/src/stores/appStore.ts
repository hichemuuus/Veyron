import { create } from 'zustand'
import type { TaskBrief, WsEvent } from '../api/types'

/**
 * Central UI store. Slices:
 *  - connection: live WS connection state
 *  - events: global rolling event log + per-task logs
 *  - tasks: lightweight cache of task briefs, kept fresh by WS deltas
 *  - confirmations: pending approval requests from the backend
 *  - toasts: transient notifications (e.g. "task submitted")
 */

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
  // connection
  connected: boolean
  setConnected: (v: boolean) => void

  // events (global)
  events: WsEvent[]
  addEvent: (ev: WsEvent) => void
  clearEventLog: () => void

  // per-task event logs (for task detail + workspace)
  taskEvents: Record<string, WsEvent[]>
  taskBriefs: Record<string, TaskBrief>

  /** Upsert a task brief (from REST or WS). */
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
}

const MAX_EVENTS = 400
const MAX_TASK_EVENTS = 300

export const useAppStore = create<AppState>((set) => ({
  connected: false,
  setConnected: (v) => set({ connected: v }),

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
      // Patch task status from task.* lifecycle events.
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
    // auto-dismiss after 4.2s
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 4200)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
