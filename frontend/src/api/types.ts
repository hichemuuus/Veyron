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
  recent_tasks: RecentTask[] | null
  recent_tasks_error?: string
  system: SystemOverview | null
  system_error?: string
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

export interface ToolParameterSchema {
  type?: string
  description?: string
  enum?: string[]
  default?: unknown
  anyOf?: Array<{ type: string }>
  [k: string]: unknown
}

export interface ToolSchema {
  name: string
  description: string
  permission: 'FREE' | 'CONFIRM' | 'RESTRICTED'
  parameters: {
    type: string
    properties?: Record<string, ToolParameterSchema>
    required?: string[]
    [k: string]: unknown
  }
}

export interface ToolListResponse {
  tools: ToolSchema[]
  count: number
}

export interface ToolInvocation {
  timestamp: string
  task_public_id: string | null
  permission: string
  inputs: Record<string, unknown>
  ok: boolean
  duration_ms: number
  error: string | null
}

export interface ToolRecentResponse {
  tool: string
  invocations: ToolInvocation[]
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

export interface WsMonitorSnapshot {
  type: 'monitor.snapshot'
  topic: string | null
  ts: number
  payload: SystemSnapshot
}

export type WsServerMessage = WsEvent | WsAck | WsError | WsMonitorSnapshot

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

// ── Memory ─────────────────────────────────────────────────────────────

export type MemoryCategory = 'user' | 'project' | 'history' | 'skill'

export interface Memory {
  public_id: string
  category: MemoryCategory | string
  content: string
  importance: number
  tags: string
  created_at: string | null
  updated_at: string | null
  last_recalled_at: string | null
  recall_count: number
  usefulness_score: number
  reliability_score: number
  success_frequency: number
  decayed: boolean
  source_task: string | null
}

export interface MemoryListResponse {
  memories: Memory[]
  count: number
  total: number
  offset: number
  limit: number
}

export interface MemorySearchResponse {
  query: string
  memories: Memory[]
  count: number
}

export interface MemoryStats {
  total: number
  by_category: Record<string, number>
  by_importance: { low: number; medium: number; high: number }
  decayed: number
  total_recalls: number
}

export interface MemoryUpdate {
  content?: string
  importance?: number
  tags?: string
}

// ── System (extended) ──────────────────────────────────────────────────

export interface SystemCpu {
  cpu_percent_overall: number
  per_cpu: number[]
  cores_logical: number
  cores_physical: number
  freq_mhz_current: number | null
  freq_mhz_max: number | null
  load_avg: number[] | null
}

export interface SystemMemory {
  total: number
  available: number
  used: number
  free: number
  percent: number
  swap_total: number
  swap_used: number
  swap_percent: number
}

export interface DiskPartition {
  device: string
  mountpoint: string
  fstype: string
  total: number
  used: number
  free: number
  percent: number
}

export interface SystemDisk {
  partitions: DiskPartition[]
}

export interface SystemHealth {
  issues: string[]
  ok: boolean
}

export interface SystemProcess {
  pid: number
  name: string
  username: string | null
  cpu_percent: number
  memory_percent: number
}

export interface SystemProcesses {
  processes: SystemProcess[]
  sort_by: string
}

// ── Monitoring snapshot (pushed via WebSocket) ────────────────────────

export interface MonitorCpu {
  percent: number
  per_cpu: number[]
  frequency_mhz: number
  count_logical: number
  count_physical: number
  load_avg: number[]
}

export interface MonitorMemory {
  total: number
  available: number
  used: number
  free: number
  percent: number
  swap_total: number
  swap_used: number
  swap_percent: number
}

export interface MonitorDisk {
  device: string
  mountpoint: string
  fstype: string
  total: number
  used: number
  free: number
  percent: number
}

export interface MonitorNetwork {
  bytes_sent: number
  bytes_recv: number
  packets_sent: number
  packets_recv: number
  bytes_sent_per_sec: number
  bytes_recv_per_sec: number
}

export interface MonitorTemperature {
  name: string
  label: string
  current: number
  high: number | null
  critical: number | null
}

export interface MonitorProcess {
  pid: number
  name: string
  username: string | null
  cpu_percent: number
  memory_percent: number
}

export interface SystemSnapshot {
  cpu: MonitorCpu
  memory: MonitorMemory
  gpu_exists: boolean
  disks: MonitorDisk[]
  network: MonitorNetwork
  temperatures: MonitorTemperature[]
  top_processes: MonitorProcess[]
  timestamp: number
}

// ── Project analysis ───────────────────────────────────────────────────

export interface ProjectTechnology {
  name: string
  confidence: number
  evidence: string[]
}

export interface ProjectIssue {
  severity: 'low' | 'medium' | 'high' | 'info' | string
  category: string
  message: string
}

export interface ProjectTreeNode {
  name: string
  type: 'dir' | 'file'
  size?: number
  children?: ProjectTreeNode[]
}

export interface ProjectAnalysis {
  root: string
  summary: string
  file_count: number
  total_size_bytes: number
  technologies: ProjectTechnology[]
  issues: ProjectIssue[]
  recommendations: string[]
  dependencies: Record<string, string[]>
  structure: ProjectTreeNode
}

// ── Learning Dashboard Types ────────────────────────────────────────────

export interface LearningOverview {
  reflection_count: number
  skill_count: number
  workflow_count: number
  benchmark_count: number
  event_count: number
  model_count: number
  timestamp: string
}

export interface LearningReflection {
  public_id: string
  task_public_id: string
  category: string
  success: boolean
  confidence: number
  planning_quality: number
  tool_selection_quality: number
  parameter_quality: number
  memory_usefulness: number
  mistake_count: number
  improvement_count: number
  tool_issue_count: number
  summary: string
  improvement_notes: string
  created_at: string | null
}

export interface LearningReflectionsResponse {
  reflections: LearningReflection[]
  total: number
  limit: number
  offset: number
}

export interface LearningSkill {
  public_id: string
  name: string
  description: string
  frequency: number
  confidence: number
  pattern_steps: Array<{ step_type: string; tool_name: string; params: Record<string, unknown> }>
  enabled: boolean
  last_used_at: string | null
  created_at: string | null
}

export interface LearningSkillsResponse {
  skills: LearningSkill[]
  total: number
  limit: number
  offset: number
}

export interface LearningSkillsStats {
  total: number
  enabled: number
  average_confidence: number
  top_skills: Array<{ name: string; frequency: number; confidence: number }>
}

export interface LearningWorkflowItem {
  public_id: string
  name: string
  description: string
  version: string
  tags: string[]
  step_count: number
  use_count: number
  success_rate: number
  source: string
  enabled: boolean
  created_at: string | null
}

export interface LearningWorkflowsResponse {
  workflows: LearningWorkflowItem[]
  total: number
  limit: number
  offset: number
}

export interface LearningWorkflowStats {
  total: number
  enabled: number
  total_uses: number
}

export interface LearningReflectionStats {
  total_reflections: number
  average_confidence: number
  average_planning_quality: number
  average_tool_selection_quality: number
  average_memory_usefulness: number
  reflections_by_category: Record<string, number>
}

export interface LearningBenchmark {
  public_id: string
  benchmark_name: string
  model_type: string
  model_version: string
  metrics: Record<string, number>
  score: number
  regressions: string[]
  duration_ms: number
  created_at: string | null
}

export interface LearningBenchmarksResponse {
  benchmarks: LearningBenchmark[]
  total: number
  limit: number
  offset: number
}

export interface LearningEvent {
  public_id: string
  event_type: string
  category: string
  summary: string
  details: Record<string, unknown>
  created_at: string | null
}

export interface LearningEventsResponse {
  events: LearningEvent[]
  total: number
  limit: number
  offset: number
}

export interface LearningModelVersion {
  version: string
  status: string
  dataset_size: number
  metrics: Record<string, number>
  path: string
  parent_version: string
  created_at: string | null
}

export interface LearningModelsResponse {
  models_by_type: Record<string, LearningModelVersion[]>
  total: number
}
