/**
 * Frontend type contract — mirrors the backend (paios/api, paios/core, paios/db).
 *
 * IMPORTANT: these event names and payload shapes were verified directly against
 * the backend Python source. The backend is authoritative; do not "fix" names
 * here to match the original brief (e.g. tool.started vs tool.request) — they
 * must stay in sync with the server.
 */

// ── Progress / task models ──────────────────────────────────────────────

export interface TaskProgress {
  total_steps: number
  completed_steps: number
  failed_steps: number
  retry_count: number
  tool_count: number
  current_step: string
  percent: number
}

/** Brief progress subset returned by list endpoints. */
export interface TaskProgressBrief {
  total_steps: number
  completed_steps: number
  failed_steps?: number
  retry_count?: number
  tool_count?: number
  current_step?: string
  percent: number
}

export type TaskStatus =
  | 'created'
  | 'planning'
  | 'running'
  | 'paused'
  | 'verifying'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type TaskMode = 'react' | 'plan'

export interface TaskBrief {
  public_id: string
  request: string
  status: TaskStatus | string
  mode: TaskMode | string
  result: string | null
  error: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  updated_at: string | null
  progress: TaskProgressBrief | null
}

export interface TaskDetail extends TaskBrief {
  history: ExecutionStep[]
  artifacts: Artifact[]
  progress: TaskProgress | null
}

export interface ExecutionStep {
  id?: number
  step_index: number
  step_type: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | string
  started_at: string | null
  finished_at: string | null
  duration_ms: number
  input_preview?: string
  output_preview?: string
  error: string | null
  retry_count: number
}

export interface Artifact {
  name: string
  type: string
  path?: string
  size?: number
  preview?: string
}

// ── Dashboard / system ──────────────────────────────────────────────────

export interface DashboardData {
  active_tasks: number
  completed_tasks: number
  failed_tasks: number
  total_tasks: number
  recent_tasks: RecentTask[]
  system: SystemOverview
  timestamp: string
}

export interface RecentTask {
  public_id: string
  request: string
  status: TaskStatus | string
  mode: TaskMode | string
  created_at: string | null
  updated_at: string | null
}

export interface SystemOverview {
  cpu_percent: number
  cpu_count: number
  memory_total: number
  memory_used: number
  memory_percent: number
  disk_percent: number
  boot_time: number
}

export interface AgentResponse {
  public_id: string
  status: string
  request: string
}

export interface TaskListResponse {
  tasks: TaskBrief[]
  count: number
}

export interface TimelineResponse {
  task_public_id: string
  steps: ExecutionStep[]
  summary: TaskProgress
}

export interface ToolInfo {
  name: string
  description: string
  permission: 'FREE' | 'CONFIRM' | 'RESTRICTED'
}

export interface ToolListResponse {
  tools: Record<string, unknown>[]
  count: number
}

// ── WebSocket ───────────────────────────────────────────────────────────

export interface WsEvent {
  type: string
  topic: string | null
  ts: number
  payload: Record<string, unknown>
}

export interface WsAck {
  type: 'ack'
  payload: {
    subscribed?: string
    unsubscribed?: string
    confirmation_id?: string
    handled?: boolean
    note?: string
  }
}

export interface WsError {
  type: 'error'
  payload: { error: string }
}

export type WsServerMessage = WsEvent | WsAck | WsError

export interface WsClientMessage {
  type: 'subscribe' | 'unsubscribe' | 'confirm.respond'
  topic?: string
  confirmation_id?: string
  approved?: boolean
  reason?: string | null
}

// ── Event catalog (verified against backend source) ─────────────────────
//
// Categories drive timeline grouping, icons, and tone in the UI. The brief
// mentioned several event names that do not exist in the backend; the names
// below are exactly what the server emits.

export type EventCategory =
  | 'task'
  | 'plan'
  | 'tool'
  | 'agent'
  | 'security'
  | 'system'

export interface EventMeta {
  label: string
  category: EventCategory
  /** 'ok' | 'active' | 'warn' | 'fail' | 'info' */
  tone: 'ok' | 'active' | 'warn' | 'fail' | 'info'
  glyph: string // single short token rendered in the timeline node
}

export const EVENT_CATALOG: Record<string, EventMeta> = {
  'task.created': { label: 'Task created', category: 'task', tone: 'info', glyph: '+' },
  'task.started': { label: 'Execution started', category: 'task', tone: 'active', glyph: '▶' },
  'task.intent': { label: 'Intent classified', category: 'task', tone: 'info', glyph: '◎' },
  'task.completed': { label: 'Task completed', category: 'task', tone: 'ok', glyph: '✓' },
  'task.failed': { label: 'Task failed', category: 'task', tone: 'fail', glyph: '✕' },
  'task.paused': { label: 'Task paused', category: 'task', tone: 'warn', glyph: '‖' },
  'task.cancelled': { label: 'Task cancelled', category: 'task', tone: 'warn', glyph: '⊘' },
  'task.cancelling': { label: 'Cancellation requested', category: 'task', tone: 'warn', glyph: '⊘' },

  'plan.start': { label: 'Planning started', category: 'plan', tone: 'active', glyph: '⟐' },
  'plan.created': { label: 'Plan generated', category: 'plan', tone: 'info', glyph: '⊞' },
  'plan.step.start': { label: 'Step started', category: 'plan', tone: 'active', glyph: '→' },
  'plan.step.complete': { label: 'Step verified', category: 'plan', tone: 'ok', glyph: '✓' },
  'plan.step.error': { label: 'Step error', category: 'plan', tone: 'warn', glyph: '!' },
  'plan.step.failed': { label: 'Step failed', category: 'plan', tone: 'fail', glyph: '✕' },
  'plan.step.tool': { label: 'Step tool call', category: 'plan', tone: 'info', glyph: '⚡' },
  'plan.replanned': { label: 'Plan regenerated', category: 'plan', tone: 'warn', glyph: '↻' },
  'plan.synthesized': { label: 'Result synthesized', category: 'plan', tone: 'ok', glyph: 'Σ' },

  'tool.request': { label: 'Tool invoked', category: 'tool', tone: 'active', glyph: '⚙' },
  'tool.result': { label: 'Tool result', category: 'tool', tone: 'info', glyph: '▤' },

  'agent.iteration': { label: 'Reasoning iteration', category: 'agent', tone: 'info', glyph: '∘' },
  'agent.thinking': { label: 'Agent computing', category: 'agent', tone: 'active', glyph: '·' },
  'agent.answer': { label: 'Answer produced', category: 'agent', tone: 'ok', glyph: '✓' },
  'agent.exhausted': { label: 'Iterations exhausted', category: 'agent', tone: 'warn', glyph: '!' },

  'security.confirm': { label: 'Approval required', category: 'security', tone: 'warn', glyph: '🔒' },
  'security.confirm.resolved': {
    label: 'Approval resolved',
    category: 'security',
    tone: 'info',
    glyph: '🔓',
  },
}

export function eventMeta(type: string): EventMeta {
  return (
    EVENT_CATALOG[type] ?? {
      label: type,
      category: 'system',
      tone: 'info',
      glyph: '·',
    }
  )
}
