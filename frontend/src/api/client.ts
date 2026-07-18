/**
 * Typed REST client for the Veyron backend.
 *
 * In dev (Vite) paths are relative to `/api` via the Vite proxy.
 * In production (Tauri) the backend runs on 127.0.0.1:8000.
 */

import type {
  AgentResponse,
  DashboardData,
  LearningBenchmarksResponse,
  LearningEventsResponse,
  LearningModelsResponse,
  LearningOverview,
  LearningReflectionStats,
  LearningReflectionsResponse,
  LearningSkillsResponse,
  LearningSkillsStats,
  LearningWorkflowsResponse,
  LearningWorkflowStats,
  Memory,
  MemoryListResponse,
  MemorySearchResponse,
  MemoryStats,
  MemoryUpdate,
  ProjectAnalysis,
  RecentTask,
  SystemCpu,
  SystemDisk,
  SystemHealth,
  SystemMemory,
  SystemOverview,
  SystemProcesses,
  TaskDetail,
  TaskListResponse,
  TimelineResponse,
  ToolListResponse,
  ToolRecentResponse,
  ToolSchema,
} from './types'

export interface RequestMetrics {
  method: string
  url: string
  status: number | null
  latency: number
  error: string | null
  retries: number
}

export interface RequestHistoryEntry {
  method: string
  path: string
  status: number | null
  duration: number
  error: string | null
  retries: number
  timestamp: number
  stack?: string
}

let _lastMetrics: RequestMetrics | null = null
let _requestHistory: RequestHistoryEntry[] = []
const MAX_HISTORY = 20

export function getLastRequestMetrics(): RequestMetrics | null {
  return _lastMetrics
}

export function getRequestHistory(): RequestHistoryEntry[] {
  return _requestHistory
}

function pushHistory(entry: RequestHistoryEntry): void {
  _requestHistory = [..._requestHistory.slice(-(MAX_HISTORY - 1)), entry]
}

const _isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

let _tauriInvoke: ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | undefined
async function getTauriInvoke() {
  if (!_tauriInvoke) {
    const m = await import('@tauri-apps/api/core')
    _tauriInvoke = m.invoke
  }
  return _tauriInvoke!
}

interface HttpResponse {
  status: number
  ok: boolean
  body: string
}

async function getFetch(): Promise<typeof fetch> {
  if (_isTauri) {
    return async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : String(input)
      const method = init?.method || 'GET'
      const headers = init?.headers ? Object.entries(init.headers as Record<string, string>) : undefined
      const body = init?.body as string | undefined
      const invoke = await getTauriInvoke()
      const result = await invoke('http_fetch', { url, method, headers, body }) as HttpResponse
      return new Response(result.body, { status: result.status, statusText: result.ok ? 'OK' : 'Error' })
    }
  }
  return fetch
}

function baseUrl(): string {
  return _isTauri ? 'http://127.0.0.1:8000/api' : '/api'
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${baseUrl()}${path}`
  const method = options.method || 'GET'
  const maxRetries = 3
  let lastError: Error | null = null
  let finalStatus: number | null = null
  let finalLatency = 0
  let terminalAttempt = 0
  const fet = await getFetch()

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, Math.min(1000 * Math.pow(2, attempt), 4000)))
    }
    const t0 = performance.now()
    terminalAttempt = attempt
    try {
      const mergedHeaders: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> | undefined),
      }
      const res = await fet(url, {
        ...options,
        headers: mergedHeaders,
      })
      finalLatency = Math.round(performance.now() - t0)
      finalStatus = res.status
      const text = await res.text()
      _lastMetrics = { method, url, status: finalStatus, latency: finalLatency, error: null, retries: attempt }

      if (!res.ok) {
        const body = text.slice(0, 200)
        _lastMetrics = { method, url, status: finalStatus, latency: finalLatency, error: body, retries: attempt }
        pushHistory({ method, path, status: finalStatus, duration: finalLatency, error: body, retries: attempt, timestamp: Date.now() })
        throw new ApiError(res.status, `API ${res.status}: ${body}`)
      }
      pushHistory({ method, path, status: finalStatus, duration: finalLatency, error: null, retries: attempt, timestamp: Date.now() })
      if (!text) return {} as T
      return JSON.parse(text) as T
    } catch (e) {
      finalLatency = Math.round(performance.now() - t0)
      lastError = e instanceof Error ? e : new Error(String(e))
      finalStatus = null
      _lastMetrics = {
        method,
        url,
        status: null,
        latency: finalLatency,
        error: lastError.message,
        retries: attempt,
      }
      if (e instanceof ApiError) {
        // Don't retry 4xx/5xx — already pushed to history above
        throw e
      }
      // Network or parse error — will retry
    }
  }

  // All retries exhausted — push terminal failure
  pushHistory({
    method,
    path,
    status: finalStatus,
    duration: finalLatency,
    error: lastError?.message ?? 'Request failed',
    retries: terminalAttempt,
    timestamp: Date.now(),
    stack: lastError?.stack,
  })
  throw lastError ?? new Error('Request failed')
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

export interface SystemResponse<T> {
  ok: boolean
  output?: string
  data?: T
  error?: string
}

export const api = {
  // ── Dashboard / system ────────────────────────────────────────────────
  async dashboard(): Promise<DashboardData> {
    const [statsRes, tasksRes, sysRes] = await Promise.allSettled([
      request<DashboardData>('/dashboard'),
      request<TaskListResponse>('/agent?limit=10'),
      request<SystemResponse<SystemOverview>>('/system/overview'),
    ])

    // Stats — from /dashboard, default to 0s on failure
    let active_tasks = 0
    let completed_tasks = 0
    let failed_tasks = 0
    let total_tasks = 0
    let timestamp = new Date().toISOString()
    if (statsRes.status === 'fulfilled') {
      const d = statsRes.value
      active_tasks = d.active_tasks ?? 0
      completed_tasks = d.completed_tasks ?? 0
      failed_tasks = d.failed_tasks ?? 0
      total_tasks = d.total_tasks ?? 0
      timestamp = d.timestamp ?? timestamp
    }

    // Recent tasks — from /agent
    let recent_tasks: RecentTask[] | null = null
    let recent_tasks_error: string | undefined
    if (tasksRes.status === 'fulfilled') {
      recent_tasks = tasksRes.value.tasks.map((t) => ({
        public_id: t.public_id,
        request: t.request,
        status: t.status,
        mode: t.mode,
        created_at: t.created_at,
        updated_at: t.updated_at,
      }))
    } else {
      recent_tasks_error =
        tasksRes.reason instanceof Error
          ? tasksRes.reason.message
          : 'Failed to load recent tasks'
    }

    // System overview — from /system/overview
    let system: SystemOverview | null = null
    let system_error: string | undefined
    if (sysRes.status === 'fulfilled') {
      const r = sysRes.value
      if (r.ok && r.data) {
        system = r.data
      } else {
        system_error = r.error || 'System overview unavailable'
      }
    } else {
      system_error =
        sysRes.reason instanceof Error
          ? sysRes.reason.message
          : 'Failed to load system info'
    }

    return {
      active_tasks,
      completed_tasks,
      failed_tasks,
      total_tasks,
      recent_tasks,
      recent_tasks_error,
      system,
      system_error,
      timestamp,
    }
  },

  systemOverview(): Promise<SystemResponse<SystemOverview>> {
    return request('/system/overview')
  },

  systemCpu(): Promise<SystemResponse<SystemCpu>> {
    return request('/system/cpu')
  },

  systemMemory(): Promise<SystemResponse<SystemMemory>> {
    return request('/system/memory')
  },

  systemDisk(): Promise<SystemResponse<SystemDisk>> {
    return request('/system/disk')
  },

  systemHealth(): Promise<SystemResponse<SystemHealth>> {
    return request('/system/health')
  },

  systemProcesses(
    count: number = 12,
    sortBy: 'cpu' | 'memory' = 'cpu',
  ): Promise<SystemResponse<SystemProcesses>> {
    return request(`/system/processes?count=${count}&sort_by=${sortBy}`)
  },

  info(): Promise<{
    version: string
    pid: number
    environment: string
    tools: string[]
    sandbox_roots: string[]
    model: { base_model: string; ollama_url: string; provider: string; remote_enabled: boolean }
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

  getTool(name: string): Promise<ToolSchema> {
    return request<ToolSchema>(`/tools/${encodeURIComponent(name)}`)
  },

  recentToolInvocations(name: string, limit: number = 20): Promise<ToolRecentResponse> {
    return request<ToolRecentResponse>(
      `/tools/${encodeURIComponent(name)}/recent?limit=${limit}`,
    )
  },

  // ── Memory ────────────────────────────────────────────────────────────
  listMemories(params?: {
    limit?: number
    offset?: number
    category?: string
    tags?: string
    min_importance?: number
    include_decayed?: boolean
  }): Promise<MemoryListResponse> {
    const q = new URLSearchParams()
    if (params?.limit != null) q.set('limit', String(params.limit))
    if (params?.offset != null) q.set('offset', String(params.offset))
    if (params?.category) q.set('category', params.category)
    if (params?.tags) q.set('tags', params.tags)
    if (params?.min_importance != null)
      q.set('min_importance', String(params.min_importance))
    if (params?.include_decayed) q.set('include_decayed', 'true')
    const qs = q.toString()
    return request<MemoryListResponse>(`/memory${qs ? `?${qs}` : ''}`)
  },

  searchMemories(query: string, params?: {
    category?: string
    tags?: string
    limit?: number
  }): Promise<MemorySearchResponse> {
    const q = new URLSearchParams()
    q.set('q', query)
    if (params?.category) q.set('category', params.category)
    if (params?.tags) q.set('tags', params.tags)
    if (params?.limit != null) q.set('limit', String(params.limit))
    return request<MemorySearchResponse>(`/memory/search?${q.toString()}`)
  },

  memoryStats(): Promise<MemoryStats> {
    return request<MemoryStats>('/memory/stats')
  },

  getMemory(publicId: string): Promise<Memory> {
    return request<Memory>(`/memory/${publicId}`)
  },

  updateMemory(publicId: string, patch: MemoryUpdate): Promise<Memory> {
    return request<Memory>(`/memory/${publicId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  deleteMemory(publicId: string): Promise<{ status: string; public_id: string }> {
    return request(`/memory/${publicId}`, { method: 'DELETE' })
  },

  // ── Projects ──────────────────────────────────────────────────────────
  analyzeProject(req: {
    path: string
    max_depth?: number
    include_hidden?: boolean
  }): Promise<ProjectAnalysis> {
    return request<ProjectAnalysis>('/projects/analyze', {
      method: 'POST',
      body: JSON.stringify({
        path: req.path,
        max_depth: req.max_depth ?? 5,
        include_hidden: req.include_hidden ?? false,
      }),
    })
  },

  // ── Learning ──────────────────────────────────────────────────────────
  learningOverview(): Promise<LearningOverview> {
    return request<LearningOverview>('/learning/overview')
  },

  learningReflections(params?: { limit?: number; offset?: number }): Promise<LearningReflectionsResponse> {
    const q = new URLSearchParams()
    if (params?.limit != null) q.set('limit', String(params.limit))
    if (params?.offset != null) q.set('offset', String(params.offset))
    const qs = q.toString()
    return request(`/learning/reflections${qs ? `?${qs}` : ''}`)
  },

  learningSkills(params?: { limit?: number; offset?: number }): Promise<LearningSkillsResponse> {
    const q = new URLSearchParams()
    if (params?.limit != null) q.set('limit', String(params.limit))
    if (params?.offset != null) q.set('offset', String(params.offset))
    const qs = q.toString()
    return request(`/learning/skills${qs ? `?${qs}` : ''}`)
  },

  learningWorkflows(params?: { limit?: number; offset?: number }): Promise<LearningWorkflowsResponse> {
    const q = new URLSearchParams()
    if (params?.limit != null) q.set('limit', String(params.limit))
    if (params?.offset != null) q.set('offset', String(params.offset))
    const qs = q.toString()
    return request(`/learning/workflows${qs ? `?${qs}` : ''}`)
  },

  learningBenchmarks(params?: { limit?: number; offset?: number }): Promise<LearningBenchmarksResponse> {
    const q = new URLSearchParams()
    if (params?.limit != null) q.set('limit', String(params.limit))
    if (params?.offset != null) q.set('offset', String(params.offset))
    const qs = q.toString()
    return request(`/learning/benchmarks${qs ? `?${qs}` : ''}`)
  },

  learningEvents(params?: { category?: string; limit?: number; offset?: number }): Promise<LearningEventsResponse> {
    const q = new URLSearchParams()
    if (params?.limit != null) q.set('limit', String(params.limit))
    if (params?.offset != null) q.set('offset', String(params.offset))
    if (params?.category) q.set('category', params.category)
    const qs = q.toString()
    return request(`/learning/events${qs ? `?${qs}` : ''}`)
  },

  learningModels(): Promise<LearningModelsResponse> {
    return request<LearningModelsResponse>('/learning/models')
  },

  learningSkillsStats(): Promise<LearningSkillsStats> {
    return request<LearningSkillsStats>('/learning/skills/stats')
  },

  learningWorkflowStats(): Promise<LearningWorkflowStats> {
    return request<LearningWorkflowStats>('/learning/workflows/stats')
  },

  learningReflectionStats(): Promise<LearningReflectionStats> {
    return request<LearningReflectionStats>('/learning/reflections/stats')
  },
}
