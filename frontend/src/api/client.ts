/**
 * Typed REST client for the PAIOS backend.
 *
 * All paths are relative to `/api` and rely on the Vite dev proxy
 * (vite.config.ts) in dev and FastAPI StaticFiles in prod.
 */

import type {
  AgentResponse,
  DashboardData,
  SystemOverview,
  TaskDetail,
  TaskListResponse,
  TimelineResponse,
  ToolListResponse,
} from './types'

const BASE = '/api'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE}${path}`
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })
  if (!res.ok) {
    let body = ''
    try {
      body = await res.text()
    } catch {
      // ignore
    }
    throw new ApiError(res.status, `API ${res.status}: ${body.slice(0, 200)}`)
  }
  // Some DELETE / control endpoints may return empty bodies; guard that.
  const text = await res.text()
  if (!text) return {} as T
  try {
    return JSON.parse(text) as T
  } catch {
    return {} as T
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface ListParams {
  limit?: number
  offset?: number
  status?: string
  mode?: string
}

export const api = {
  // ── Dashboard / system ────────────────────────────────────────────────
  dashboard(): Promise<DashboardData> {
    return request<DashboardData>('/dashboard')
  },

  systemOverview(): Promise<{ ok: boolean; output?: string; data?: SystemOverview }> {
    return request('/system/overview')
  },

  systemHealth(): Promise<{ ok: boolean; output?: string; data?: { issues: string[]; ok: boolean } }> {
    return request('/system/health')
  },

  info(): Promise<{
    version: string
    tools: string[]
    model: { base_model: string; ollama_url: string }
  }> {
    return request('/info')
  },

  // ── Agent / tasks ─────────────────────────────────────────────────────
  createTask(request_text: string): Promise<AgentResponse> {
    return request<AgentResponse>('/agent', {
      method: 'POST',
      body: JSON.stringify({ request: request_text }),
    })
  },

  getTask(publicId: string): Promise<TaskDetail> {
    return request<TaskDetail>(`/agent/${publicId}`)
  },

  listTasks(params?: ListParams): Promise<TaskListResponse> {
    const q = new URLSearchParams()
    if (params?.limit != null) q.set('limit', String(params.limit))
    if (params?.offset != null) q.set('offset', String(params.offset))
    if (params?.status) q.set('status', params.status)
    if (params?.mode) q.set('mode', params.mode)
    const qs = q.toString()
    return request<TaskListResponse>(`/agent${qs ? `?${qs}` : ''}`)
  },

  getTimeline(publicId: string): Promise<TimelineResponse> {
    return request<TimelineResponse>(`/agent/${publicId}/timeline`)
  },

  cancelTask(publicId: string): Promise<{ status: string; public_id: string }> {
    return request(`/agent/${publicId}/cancel`, { method: 'POST' })
  },

  pauseTask(publicId: string): Promise<{ status: string; public_id: string }> {
    return request(`/agent/${publicId}/pause`, { method: 'POST' })
  },

  resumeTask(publicId: string): Promise<{ status: string; public_id: string }> {
    return request(`/agent/${publicId}/resume`, { method: 'POST' })
  },

  deleteTask(publicId: string): Promise<{ status: string; public_id: string }> {
    return request(`/agent/${publicId}`, { method: 'DELETE' })
  },

  // ── Tools ─────────────────────────────────────────────────────────────
  listTools(): Promise<ToolListResponse> {
    return request<ToolListResponse>('/tools')
  },
}
