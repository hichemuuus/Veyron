import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  LearningBenchmark,
  LearningEvent,
  LearningModelVersion,
  LearningOverview,
  LearningReflection,
  LearningSkill,
  LearningWorkflowItem,
} from '../api/types'
import {
  LoadingSpinner,
  ErrorBox,
  EmptyState,
} from '../components/ui'
import { Stat } from '../components/ui/Stat'
import { fmtRelative } from '../lib/format'

type TabId = 'reflections' | 'skills' | 'workflows' | 'benchmarks' | 'events' | 'models'

const TABS: { id: TabId; label: string }[] = [
  { id: 'reflections', label: 'Reflections' },
  { id: 'skills', label: 'Skills' },
  { id: 'workflows', label: 'Workflows' },
  { id: 'benchmarks', label: 'Benchmarks' },
  { id: 'events', label: 'Events' },
  { id: 'models', label: 'Models' },
]

interface TabState {
  loading: boolean
  error: string | null
}

type TabDataMap = {
  reflections: LearningReflection[]
  skills: LearningSkill[]
  workflows: LearningWorkflowItem[]
  benchmarks: LearningBenchmark[]
  events: LearningEvent[]
  models: LearningModelsTabData | null
}

interface LearningModelsTabData {
  models_by_type: Record<string, LearningModelVersion[]>
  total: number
}

const INITIAL_TAB_STATE: TabState = { loading: false, error: null }

export function LearningDashboardPage() {
  const [overview, setOverview] = useState<LearningOverview | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabId>('reflections')

  // Per-tab data and state
  const [tabData, setTabData] = useState<Partial<TabDataMap>>({})
  const [tabState, setTabState] = useState<Record<TabId, TabState>>({
    reflections: { ...INITIAL_TAB_STATE },
    skills: { ...INITIAL_TAB_STATE },
    workflows: { ...INITIAL_TAB_STATE },
    benchmarks: { ...INITIAL_TAB_STATE },
    events: { ...INITIAL_TAB_STATE },
    models: { ...INITIAL_TAB_STATE },
  })

  // Track which tabs have been loaded at least once (avoids refetching on re-mount)
  const loadedTabs = useRef<Set<TabId>>(new Set())

  // ── Fetch overview on mount ─────────────────────────────────────────────
  const fetchOverview = useCallback(async () => {
    setOverviewLoading(true)
    setOverviewError(null)
    try {
      const data = await api.learningOverview()
      setOverview(data)
    } catch (e) {
      setOverviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setOverviewLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchOverview()
  }, [fetchOverview])

  // ── Fetch data for a given tab ───────────────────────────────────────────
  const fetchTab = useCallback(async (tabId: TabId) => {
    if (loadedTabs.current.has(tabId)) return

    setTabState((prev) => ({ ...prev, [tabId]: { loading: true, error: null } }))

    try {
      let data: unknown
      switch (tabId) {
        case 'reflections': {
          const res = await api.learningReflections({ limit: 50 })
          data = res.reflections
          break
        }
        case 'skills': {
          const res = await api.learningSkills({ limit: 50 })
          data = res.skills
          break
        }
        case 'workflows': {
          const res = await api.learningWorkflows({ limit: 50 })
          data = res.workflows
          break
        }
        case 'benchmarks': {
          const res = await api.learningBenchmarks({ limit: 50 })
          data = res.benchmarks
          break
        }
        case 'events': {
          const res = await api.learningEvents({ limit: 50 })
          data = res.events
          break
        }
        case 'models': {
          const res = await api.learningModels()
          data = { models_by_type: res.models_by_type, total: res.total }
          break
        }
      }
      setTabData((prev) => ({ ...prev, [tabId]: data as never }))
      loadedTabs.current.add(tabId)
      setTabState((prev) => ({ ...prev, [tabId]: { loading: false, error: null } }))
    } catch (e) {
      setTabState((prev) => ({
        ...prev,
        [tabId]: { loading: false, error: e instanceof Error ? e.message : String(e) },
      }))
    }
  }, [])

  // Fetch active tab data when tab changes
  useEffect(() => {
    fetchTab(activeTab)
  }, [activeTab, fetchTab])

  // ── Helpers ──────────────────────────────────────────────────────────────
  const currentData = tabData[activeTab]
  const currentState = tabState[activeTab]

  const retryOverview = useCallback(() => {
    fetchOverview()
  }, [fetchOverview])

  const retryTab = useCallback(() => {
    const tab = activeTab
    loadedTabs.current.delete(tab)
    setTabData((prev) => ({ ...prev, [tab]: undefined }))
    fetchTab(tab)
  }, [activeTab, fetchTab])

  return (
    <div className="mx-auto max-w-6xl px-8 py-8 page-enter">
      {/* Header */}
      <header className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-display-sm font-medium text-ink-900">Learning</h1>
          <p className="mt-1 text-sm text-ink-500">
            Reflections, skills, workflows, benchmarks, and model versions learned over time.
          </p>
        </div>
      </header>

      {/* Overview error */}
      {overviewError ? (
        <div className="mt-5">
          <ErrorBox message={overviewError} onRetry={retryOverview} />
        </div>
      ) : null}

      {/* Overview stat strip */}
      <section className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6">
        <Stat
          label="Reflections"
          value={overviewLoading && !overview ? '—' : overview?.reflection_count ?? 0}
          tone="default"
          icon={<span className="h-2 w-2 rounded-full bg-sig-500" />}
        />
        <Stat
          label="Skills"
          value={overviewLoading && !overview ? '—' : overview?.skill_count ?? 0}
          tone="default"
        />
        <Stat
          label="Workflows"
          value={overviewLoading && !overview ? '—' : overview?.workflow_count ?? 0}
          tone="default"
        />
        <Stat
          label="Benchmarks"
          value={overviewLoading && !overview ? '—' : overview?.benchmark_count ?? 0}
          tone="default"
        />
        <Stat
          label="Events"
          value={overviewLoading && !overview ? '—' : overview?.event_count ?? 0}
          tone="default"
        />
        <Stat
          label="Models"
          value={overviewLoading && !overview ? '—' : overview?.model_count ?? 0}
          tone="default"
        />
      </section>

      {/* Tab bar */}
      <div className="mt-8">
        <div className="flex items-center gap-1 rounded-lg border border-ink-200 bg-ink-200/40 p-0.5 w-fit">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`focus-ring rounded-md px-3 py-1.5 text-[11px] font-medium uppercase tracking-wider transition-colors ${
                activeTab === tab.id
                  ? 'bg-sig-500/15 text-sig-700'
                  : 'text-ink-500 hover:bg-ink-100/60 hover:text-ink-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="mt-5 panel p-5">
        {!currentData && !currentState.loading ? (
          <LoadingSpinner label={`Loading ${activeTab}`} />
        ) : currentState.loading && !currentData ? (
          <LoadingSpinner label={`Loading ${activeTab}`} />
        ) : currentState.error ? (
          <ErrorBox message={currentState.error} onRetry={retryTab} />
        ) : currentData && Array.isArray(currentData) && currentData.length === 0 ? (
          <EmptyState
            title={`No ${activeTab} yet`}
            hint={emptyHint(activeTab)}
          />
        ) : activeTab === 'models' ? (
          renderModels(currentData as LearningModelsTabData | undefined)
        ) : currentData ? (
          renderTable(activeTab, currentData)
        ) : null}
      </div>
    </div>
  )
}

// ── Table renderers ───────────────────────────────────────────────────────

function renderTable(tabId: TabId, data: unknown) {
  switch (tabId) {
    case 'reflections':
      return <ReflectionsTable reflections={(data as LearningReflection[]) ?? []} />
    case 'skills':
      return <SkillsTable skills={(data as LearningSkill[]) ?? []} />
    case 'workflows':
      return <WorkflowsTable workflows={(data as LearningWorkflowItem[]) ?? []} />
    case 'benchmarks':
      return <BenchmarksTable benchmarks={(data as LearningBenchmark[]) ?? []} />
    case 'events':
      return <EventsTable events={(data as LearningEvent[]) ?? []} />
    default:
      return null
  }
}

// ── Reflections Table ─────────────────────────────────────────────────────

function ReflectionsTable({ reflections }: { reflections: LearningReflection[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-left">
        <colgroup>
          <col className="w-auto min-w-[120px]" />
          <col className="w-[10ch]" />
          <col className="w-[12ch]" />
          <col className="w-[10ch]" />
          <col className="w-[10ch]" />
          <col className="w-[12ch]" />
          <col className="w-[16ch]" />
        </colgroup>
        <thead>
          <tr className="hud-label border-b border-ink-200/70">
            <th className="py-2.5 pr-3 font-medium">Summary</th>
            <th className="py-2.5 pr-3 font-medium">Result</th>
            <th className="py-2.5 pr-3 font-medium">Confidence</th>
            <th className="py-2.5 pr-3 font-medium">Planning</th>
            <th className="py-2.5 pr-3 font-medium">Tool Sel.</th>
            <th className="py-2.5 pr-3 font-medium">Category</th>
            <th className="py-2.5 pr-3 font-medium">Timestamp</th>
          </tr>
        </thead>
        <tbody>
          {reflections.map((r) => (
            <tr key={r.public_id} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-100/50">
              <td className="text-wrap-safe py-2.5 pr-3 text-ink-700">
                <span className="line-clamp-2">{r.summary || '—'}</span>
              </td>
              <td className="py-2.5 pr-3">
                <span
                  className={`inline-block rounded-full px-1.5 py-px text-[10px] font-medium uppercase ${
                    r.success
                      ? 'border border-ok-500/40 text-ok-600 bg-ok-500/8'
                      : 'border border-bad-500/40 text-bad-600 bg-bad-500/8'
                  }`}
                >
                  {r.success ? 'Pass' : 'Fail'}
                </span>
              </td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">
                {(r.confidence * 100).toFixed(0)}%
              </td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">
                {r.planning_quality != null ? r.planning_quality.toFixed(1) : '—'}
              </td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">
                {r.tool_selection_quality != null ? r.tool_selection_quality.toFixed(1) : '—'}
              </td>
              <td className="py-2.5 pr-3 truncate text-ink-500" title={r.category}>{r.category || '—'}</td>
              <td className="py-2.5 pr-3 text-ink-400 data-mono">{fmtRelative(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Skills Table ──────────────────────────────────────────────────────────

function SkillsTable({ skills }: { skills: LearningSkill[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-left">
        <colgroup>
          <col />
          <col className="w-[12ch]" />
          <col className="w-[12ch]" />
          <col className="w-auto min-w-[120px]" />
          <col className="w-[12ch]" />
          <col className="w-[16ch]" />
        </colgroup>
        <thead>
          <tr className="hud-label border-b border-ink-200/70">
            <th className="py-2.5 pr-3 font-medium">Name</th>
            <th className="py-2.5 pr-3 font-medium">Frequency</th>
            <th className="py-2.5 pr-3 font-medium">Confidence</th>
            <th className="py-2.5 pr-3 font-medium">Description</th>
            <th className="py-2.5 pr-3 font-medium">Status</th>
            <th className="py-2.5 pr-3 font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {skills.map((s) => (
            <tr key={s.public_id} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-100/50">
              <td className="py-2.5 pr-3 font-mono font-medium text-ink-700">{s.name}</td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">{s.frequency ?? 0}</td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">
                {s.confidence != null ? (s.confidence * 100).toFixed(0) : '—'}%
              </td>
              <td className="text-wrap-safe py-2.5 pr-3 text-ink-500">
                <span className="line-clamp-2">{s.description || '—'}</span>
              </td>
              <td className="py-2.5 pr-3">
                <span
                  className={`inline-block rounded-full px-1.5 py-px text-[10px] font-medium uppercase ${
                    s.enabled
                      ? 'border border-ok-500/40 text-ok-600 bg-ok-500/8'
                      : 'border border-ink-300 text-ink-500 bg-ink-100'
                  }`}
                >
                  {s.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </td>
              <td className="py-2.5 pr-3 text-ink-400 data-mono">{fmtRelative(s.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Workflows Table ───────────────────────────────────────────────────────

function WorkflowsTable({ workflows }: { workflows: LearningWorkflowItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-left">
        <colgroup>
          <col />
          <col className="w-[10ch]" />
          <col className="w-[8ch]" />
          <col className="w-[8ch]" />
          <col className="w-[14ch]" />
          <col className="w-[14ch]" />
          <col className="w-[10ch]" />
        </colgroup>
        <thead>
          <tr className="hud-label border-b border-ink-200/70">
            <th className="py-2.5 pr-3 font-medium">Name</th>
            <th className="py-2.5 pr-3 font-medium">Version</th>
            <th className="py-2.5 pr-3 font-medium">Steps</th>
            <th className="py-2.5 pr-3 font-medium">Uses</th>
            <th className="py-2.5 pr-3 font-medium">Success Rate</th>
            <th className="py-2.5 pr-3 font-medium">Source</th>
            <th className="py-2.5 pr-3 font-medium">Enabled</th>
          </tr>
        </thead>
        <tbody>
          {workflows.map((w) => (
            <tr key={w.public_id} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-100/50">
              <td className="py-2.5 pr-3 font-mono font-medium text-ink-700">{w.name}</td>
              <td className="py-2.5 pr-3 data-mono text-ink-500">{w.version || '—'}</td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">{w.step_count ?? 0}</td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">{w.use_count ?? 0}</td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">
                {w.success_rate != null ? `${(w.success_rate * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="py-2.5 pr-3 text-ink-500">{w.source || '—'}</td>
              <td className="py-2.5 pr-3">
                <span
                  className={`inline-block rounded-full px-1.5 py-px text-[10px] font-medium uppercase ${
                    w.enabled
                      ? 'border border-ok-500/40 text-ok-600 bg-ok-500/8'
                      : 'border border-ink-300 text-ink-500 bg-ink-100'
                  }`}
                >
                  {w.enabled ? 'On' : 'Off'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Benchmarks Table ──────────────────────────────────────────────────────

function BenchmarksTable({ benchmarks }: { benchmarks: LearningBenchmark[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-left">
        <colgroup>
          <col />
          <col />
          <col className="w-[10ch]" />
          <col className="w-auto min-w-[100px]" />
          <col className="w-auto min-w-[100px]" />
          <col className="w-[16ch]" />
        </colgroup>
        <thead>
          <tr className="hud-label border-b border-ink-200/70">
            <th className="py-2.5 pr-3 font-medium">Benchmark</th>
            <th className="py-2.5 pr-3 font-medium">Model</th>
            <th className="py-2.5 pr-3 font-medium">Score</th>
            <th className="py-2.5 pr-3 font-medium">Metrics</th>
            <th className="py-2.5 pr-3 font-medium">Regressions</th>
            <th className="py-2.5 pr-3 font-medium">Timestamp</th>
          </tr>
        </thead>
        <tbody>
          {benchmarks.map((b) => (
            <tr key={b.public_id} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-100/50">
              <td className="py-2.5 pr-3 font-mono font-medium text-ink-700">{b.benchmark_name}</td>
              <td className="py-2.5 pr-3 text-ink-500">
                {b.model_type}{b.model_version ? ` (${b.model_version})` : ''}
              </td>
              <td className="py-2.5 pr-3 data-mono text-ink-600">
                {b.score != null ? b.score.toFixed(2) : '—'}
              </td>
              <td className="max-w-[180px] py-2.5 pr-3 truncate text-ink-500">
                {b.metrics ? formatMetrics(b.metrics) : '—'}
              </td>
              <td className="py-2.5 pr-3 text-ink-500">
                {b.regressions && b.regressions.length > 0
                  ? b.regressions.slice(0, 2).join(', ') + (b.regressions.length > 2 ? '…' : '')
                  : '—'}
              </td>
              <td className="py-2.5 pr-3 text-ink-400 data-mono">{fmtRelative(b.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Events Table ──────────────────────────────────────────────────────────

function EventsTable({ events }: { events: LearningEvent[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-left">
        <colgroup>
          <col />
          <col className="w-[14ch]" />
          <col />
          <col className="w-[16ch]" />
        </colgroup>
        <thead>
          <tr className="hud-label border-b border-ink-200/70">
            <th className="py-2.5 pr-3 font-medium">Event Type</th>
            <th className="py-2.5 pr-3 font-medium">Category</th>
            <th className="py-2.5 pr-3 font-medium">Summary</th>
            <th className="py-2.5 pr-3 font-medium">Timestamp</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.public_id} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-100/50">
              <td className="py-2.5 pr-3 font-mono font-medium text-ink-700">{e.event_type}</td>
              <td className="py-2.5 pr-3 text-ink-500">{e.category || '—'}</td>
              <td className="max-w-[300px] py-2.5 pr-3 truncate text-ink-600">
                {e.summary || '—'}
              </td>
              <td className="py-2.5 pr-3 text-ink-400 data-mono">{fmtRelative(e.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Models (grouped by type) ──────────────────────────────────────────────

function renderModels(data: LearningModelsTabData | undefined) {
  if (!data) {
    return <LoadingSpinner label="Loading models" />
  }

  const types = Object.keys(data.models_by_type ?? {})
  if (types.length === 0) {
    return <EmptyState title="No models" hint="No model versions have been registered yet." />
  }

  return (
    <div className="flex flex-col gap-6">
      {types.map((type) => {
        const versions = data.models_by_type[type]
        return (
          <div key={type}>
            <div className="mb-3 flex items-center gap-2">
              <h3 className="font-display text-sm font-medium text-ink-900">{type}</h3>
              <span className="data-mono text-[11px] text-ink-400">{versions.length} version(s)</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full table-fixed border-collapse text-left">
                <colgroup>
                  <col className="w-[10ch]" />
                  <col className="w-[12ch]" />
                  <col />
                  <col className="w-auto min-w-[100px]" />
                  <col className="w-[10ch]" />
                </colgroup>
                <thead>
                  <tr className="hud-label border-b border-ink-200/70">
                    <th className="py-2 pr-3 font-medium">Version</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">Dataset Size</th>
                    <th className="py-2 pr-3 font-medium">Metrics</th>
                    <th className="py-2 pr-3 font-medium">Parent</th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => (
                    <tr key={v.version} className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-100/50">
                      <td className="py-2 pr-3 data-mono text-ink-700">{v.version}</td>
                      <td className="py-2 pr-3">
                        <span className={`inline-block rounded-full px-1.5 py-px text-[10px] font-medium uppercase ${
                          v.status === 'active' || v.status === 'ready'
                            ? 'border border-ok-500/40 text-ok-600 bg-ok-500/8'
                            : v.status === 'training'
                            ? 'border border-sig-500/40 text-sig-600 bg-sig-500/8'
                            : 'border border-ink-300 text-ink-500 bg-ink-100'
                        }`}>
                          {v.status || 'unknown'}
                        </span>
                      </td>
                      <td className="py-2 pr-3 data-mono text-ink-600">
                        {v.dataset_size != null ? `${v.dataset_size.toLocaleString()} samples` : '—'}
                      </td>
                      <td className="text-wrap-safe py-2 pr-3 text-ink-500">
                        <span className="line-clamp-2">{v.metrics ? formatMetrics(v.metrics) : '—'}</span>
                      </td>
                      <td className="py-2 pr-3 data-mono text-ink-500">
                        {v.parent_version || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────

function formatMetrics(metrics: Record<string, number>): string {
  const entries = Object.entries(metrics)
  if (entries.length === 0) return '—'
  return entries
    .slice(0, 3)
    .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(3) : v}`)
    .join(', ') + (entries.length > 3 ? '…' : '')
}

function emptyHint(tabId: TabId): string {
  switch (tabId) {
    case 'reflections':
      return 'Reflections are generated after tasks complete. Run some tasks to see reflections appear here.'
    case 'skills':
      return 'Skills are extracted from repeated successful patterns. Complete more tasks to build up skills.'
    case 'workflows':
      return 'Workflows are captured from multi-step task sequences. Execute complex tasks to generate workflows.'
    case 'benchmarks':
      return 'Benchmarks run automatically during model evaluations. No results recorded yet.'
    case 'events':
      return 'Learning events track model training and evaluation milestones. They will appear here as the system learns.'
    case 'models':
      return 'Model versions are registered when training completes. No models have been trained yet.'
    default:
      return 'No data available yet.'
  }
}
