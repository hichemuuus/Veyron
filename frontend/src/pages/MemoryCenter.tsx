import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Memory, MemoryStats, MemoryUpdate } from '../api/types'
import { useAppStore } from '../stores/appStore'
import {
  LoadingSpinner,
  ErrorBox,
  EmptyState,
  Button,
} from '../components/ui'
import { Stat } from '../components/ui/Stat'
import { fmtRelative, fmtPct } from '../lib/format'

const CATEGORIES = ['all', 'user', 'project', 'history', 'skill'] as const
type CategoryFilter = (typeof CATEGORIES)[number]

const IMPORTANCE_FILTERS = [
  { label: 'all', min: 0.0 },
  { label: 'high', min: 0.67 },
  { label: 'medium', min: 0.34 },
  { label: 'low', min: 0.0 },
] as const
type ImportanceKey = 'all' | 'high' | 'medium' | 'low'

export function MemoryCenterPage() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingStats, setLoadingStats] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<CategoryFilter>('all')
  const [importance, setImportance] = useState<ImportanceKey>('all')
  const [includeDecayed, setIncludeDecayed] = useState(false)
  const [editing, setEditing] = useState<Memory | null>(null)
  const pushToast = useAppStore((s) => s.pushToast)

  const loadStats = useCallback(async () => {
    setLoadingStats(true)
    try {
      const s = await api.memoryStats()
      setStats(s)
    } catch {
      // Stats are best-effort; ignore failures.
    } finally {
      setLoadingStats(false)
    }
  }, [])

  const loadMemories = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const trimmed = query.trim()
      const categoryParam = category === 'all' ? undefined : category
      const minImportance =
        importance === 'all' ? undefined : IMPORTANCE_FILTERS.find((f) => f.label === importance)?.min
      if (trimmed) {
        const res = await api.searchMemories(trimmed, {
          category: categoryParam,
          limit: 100,
        })
        // Apply local importance + decay filters on top of search results.
        let filtered = res.memories
        if (minImportance != null) filtered = filtered.filter((m) => m.importance >= minImportance)
        if (!includeDecayed) filtered = filtered.filter((m) => !m.decayed)
        setMemories(filtered)
      } else {
        const res = await api.listMemories({
          limit: 100,
          category: categoryParam,
          min_importance: minImportance,
          include_decayed: includeDecayed,
        })
        setMemories(res.memories)
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [query, category, importance, includeDecayed])

  useEffect(() => {
    loadStats()
  }, [loadStats])

  useEffect(() => {
    loadMemories()
  }, [loadMemories])

  async function handleSave(updated: MemoryUpdate, mem: Memory) {
    try {
      await api.updateMemory(mem.public_id, updated)
      pushToast('ok', 'Memory updated')
      setEditing(null)
      await Promise.all([loadMemories(), loadStats()])
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      pushToast('fail', `Update failed: ${msg}`)
    }
  }

  async function handleDelete(mem: Memory) {
    if (!confirm(`Delete this ${mem.category} memory? This cannot be undone.`)) return
    try {
      await api.deleteMemory(mem.public_id)
      pushToast('ok', 'Memory deleted')
      await Promise.all([loadMemories(), loadStats()])
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      pushToast('fail', `Delete failed: ${msg}`)
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-8 page-enter">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-display-sm font-medium text-ink-900">Memory</h1>
          <p className="mt-1 text-sm text-ink-500">
            What I remember. Browse, search, refine, and prune by importance.
          </p>
        </div>
        <button
          onClick={() => Promise.all([loadMemories(), loadStats()])}
          className="focus-ring rounded-lg border border-ink-200 bg-white px-3.5 py-2 text-xs font-medium text-ink-600 transition-colors hover:bg-ink-50"
        >
          ↻ Refresh
        </button>
      </header>

      {/* Stats strip */}
      <section className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-5">
        <Stat
          label="Total memories"
          value={loadingStats ? '—' : stats?.total ?? 0}
          tone="default"
        />
        <Stat
          label="High importance"
          value={loadingStats ? '—' : stats?.by_importance.high ?? 0}
          tone="ok"
        />
        <Stat
          label="Decaying"
          value={loadingStats ? '—' : stats?.decayed ?? 0}
          tone={stats && stats.decayed > 0 ? 'warn' : 'default'}
        />
        <Stat
          label="Recalls"
          value={loadingStats ? '—' : stats?.total_recalls ?? 0}
          tone="active"
        />
        <Stat
          label="Categories"
          value={loadingStats ? '—' : Object.keys(stats?.by_category ?? {}).length}
          sub={stats ? Object.entries(stats.by_category).map(([k, v]) => `${k}:${v}`).join(' · ') : undefined}
        />
      </section>

      {/* Filters */}
      <section className="panel mt-5 p-3.5">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search memory…"
            className="focus-ring h-10 flex-1 rounded-lg border border-ink-200 bg-ink-50/50 px-3.5 text-sm text-ink-900 placeholder:text-ink-400"
          />
          <div className="flex items-center gap-1 rounded-lg border border-ink-200 bg-white p-0.5">
            {CATEGORIES.map((c) => (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={`focus-ring rounded-md px-2.5 py-1 text-[11px] font-medium uppercase transition-colors ${
                  category === c ? 'bg-sig-500/15 text-sig-700' : 'text-ink-500 hover:text-ink-800'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1 rounded-lg border border-ink-200 bg-white p-0.5">
            {IMPORTANCE_FILTERS.map((f) => (
              <button
                key={f.label}
                onClick={() => setImportance(f.label as ImportanceKey)}
                className={`focus-ring rounded-md px-2.5 py-1 text-[11px] font-medium uppercase transition-colors ${
                  importance === f.label
                    ? 'bg-violet-500/15 text-violet-600'
                    : 'text-ink-500 hover:text-ink-800'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500">
            <input
              type="checkbox"
              checked={includeDecayed}
              onChange={(e) => setIncludeDecayed(e.target.checked)}
              className="accent-warn-500"
            />
            show decayed
          </label>
        </div>
      </section>

      {error ? (
        <div className="mt-5">
          <ErrorBox message={error} onRetry={loadMemories} />
        </div>
      ) : null}

      {/* Memory list */}
      <section className="mt-5">
        {loading ? (
          <div className="panel">
            <LoadingSpinner label="Loading memories" />
          </div>
        ) : memories.length === 0 ? (
          <div className="panel">
            <EmptyState
              icon="✦"
              title="No memories match"
              hint="Try a different search, category, or importance filter. I create memories while reflecting on tasks."
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {memories.map((m) => (
              <MemoryCard
                key={m.public_id}
                memory={m}
                onEdit={() => setEditing(m)}
                onDelete={() => handleDelete(m)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Edit modal */}
      {editing ? (
        <EditMemoryModal
          memory={editing}
          onCancel={() => setEditing(null)}
          onSave={(patch) => handleSave(patch, editing)}
        />
      ) : null}
    </div>
  )
}

const CATEGORY_STYLE: Record<string, string> = {
  user: 'text-sig-700 border-sig-500/30 bg-sig-50',
  project: 'text-violet-600 border-violet-500/30 bg-violet-500/8',
  skill: 'text-ok-600 border-ok-500/30 bg-ok-500/8',
  history: 'text-ink-500 border-ink-300 bg-ink-100',
}

function MemoryCard({
  memory,
  onEdit,
  onDelete,
}: {
  memory: Memory
  onEdit: () => void
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const tone = memory.importance >= 0.67 ? 'ok' : memory.importance >= 0.34 ? 'warn' : 'idle'
  return (
    <div
      className={`panel flex flex-col p-4 transition-shadow hover:shadow-card-lg ${
        memory.decayed ? 'opacity-60' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full border px-2 py-px text-[10px] font-medium uppercase ${
              CATEGORY_STYLE[memory.category] ?? CATEGORY_STYLE.history
            }`}
          >
            {memory.category}
          </span>
          {memory.decayed ? (
            <span className="rounded-full border border-warn-500/40 bg-warn-500/10 px-2 py-px text-[9px] font-medium uppercase text-warn-600">
              decayed
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="data-mono text-[10px] text-ink-400">
            imp {fmtPct(memory.importance * 100, 0)}
          </span>
          <div className="h-1.5 w-12 overflow-hidden rounded-full bg-ink-200">
            <div
              className={`h-full ${
                tone === 'ok'
                  ? 'bg-ok-500'
                  : tone === 'warn'
                  ? 'bg-warn-500'
                  : 'bg-ink-300'
              }`}
              style={{ width: `${memory.importance * 100}%` }}
            />
          </div>
        </div>
      </div>

      <p
        className={`mt-3 text-sm leading-relaxed text-ink-700 ${
          expanded ? '' : 'line-clamp-3'
        }`}
      >
        {memory.content}
      </p>
      {memory.content.length > 180 ? (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-1.5 self-start text-[11px] font-medium text-sig-600 hover:underline"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      ) : null}

      {/* Quality + recall row */}
      <div className="mt-3 grid grid-cols-3 gap-2 border-t border-ink-200/70 pt-3">
        <Quality label="Useful" value={memory.usefulness_score} />
        <Quality label="Reliable" value={memory.reliability_score} />
        <Quality label="Success" value={memory.success_frequency} />
      </div>

      {/* Meta row */}
      <div className="mt-3 flex items-center justify-between text-[10px] text-ink-400">
        <div className="flex items-center gap-2">
          <span title="created">{fmtRelative(memory.created_at)}</span>
          <span>·</span>
          <span title="recall count">↻ {memory.recall_count}</span>
          {memory.last_recalled_at ? (
            <>
              <span>·</span>
              <span title="last recalled">{fmtRelative(memory.last_recalled_at)}</span>
            </>
          ) : null}
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={onEdit}>
            Edit
          </Button>
          <Button variant="ghost" size="sm" onClick={onDelete}>
            Delete
          </Button>
        </div>
      </div>

      {memory.tags ? (
        <div className="mt-3 flex flex-wrap gap-1">
          {memory.tags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean)
            .map((t) => (
              <span
                key={t}
                className="rounded-md border border-ink-200 bg-ink-50 px-1.5 py-0.5 text-[10px] text-ink-500"
              >
                #{t}
              </span>
            ))}
        </div>
      ) : null}
    </div>
  )
}

function Quality({ label, value }: { label: string; value: number }) {
  const tone = value >= 0.67 ? 'text-ok-600' : value >= 0.34 ? 'text-warn-600' : 'text-ink-500'
  return (
    <div className="flex flex-col">
      <span className="hud-label">{label}</span>
      <span className={`data-mono mt-0.5 text-[11px] ${tone}`}>{fmtPct(value * 100, 0)}</span>
    </div>
  )
}

function EditMemoryModal({
  memory,
  onCancel,
  onSave,
}: {
  memory: Memory
  onCancel: () => void
  onSave: (patch: MemoryUpdate) => void
}) {
  const [content, setContent] = useState(memory.content)
  const [importance, setImportance] = useState(memory.importance)
  const [tags, setTags] = useState(memory.tags)
  const dirty =
    content !== memory.content ||
    Math.abs(importance - memory.importance) > 0.001 ||
    tags !== memory.tags

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/30 p-4 backdrop-blur-sm">
      <div className="panel w-full max-w-2xl p-6 shadow-card-lg">
        <div className="flex items-center justify-between">
          <span className="hud-label text-sig-700">Edit memory</span>
          <span className="font-mono text-[10px] text-ink-400">
            {memory.public_id.slice(0, 12)}…
          </span>
        </div>

        <div className="mt-4">
          <label className="hud-label">Content</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={8}
            className="focus-ring mt-1.5 w-full resize-y rounded-lg border border-ink-200 bg-ink-50/50 p-3 text-sm leading-relaxed text-ink-900"
          />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <div>
            <label className="hud-label">Importance</label>
            <div className="mt-2 flex items-center gap-2">
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={importance}
                onChange={(e) => setImportance(Number(e.target.value))}
                className="flex-1 accent-sig-500"
              />
              <span className="data-mono w-12 text-right text-sm text-ink-800">
                {fmtPct(importance * 100, 0)}
              </span>
            </div>
          </div>
          <div>
            <label className="hud-label">Tags (comma-separated)</label>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="tag1, tag2"
              className="focus-ring mt-1.5 w-full rounded-lg border border-ink-200 bg-ink-50/50 px-3 py-2 text-sm text-ink-900 placeholder:text-ink-400"
            />
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => onSave({ content, importance, tags })}
            disabled={!dirty || !content.trim()}
          >
            Save changes
          </Button>
        </div>
      </div>
    </div>
  )
}
