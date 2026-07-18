import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ToolInvocation, ToolSchema } from '../api/types'
import { useAppStore } from '../stores/appStore'
import {
  LoadingSpinner,
  ErrorBox,
  EmptyState,
  Button,
} from '../components/ui'
import { StatusBadge } from '../components/ui/StatusBadge'
import { fmtRelative, fmtMs, fmtClock } from '../lib/format'

const PERMISSION_TONE: Record<string, 'ok' | 'warn' | 'fail'> = {
  FREE: 'ok',
  CONFIRM: 'warn',
  RESTRICTED: 'fail',
}

const PERMISSION_NOTE: Record<string, string> = {
  FREE: 'Runs on its own — no approval needed.',
  CONFIRM: 'Needs your approval before running.',
  RESTRICTED: 'Needs approval and a documented reason.',
}

export function ToolCenterPage() {
  const [tools, setTools] = useState<ToolSchema[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const pushToast = useAppStore((s) => s.pushToast)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await api.listTools()
      setTools(res.tools)
      if (!selected && res.tools.length > 0) setSelected(res.tools[0].name)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="mx-auto max-w-6xl px-8 py-8 page-enter">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="font-display text-display-sm font-medium text-ink-900">Tools</h1>
          <p className="mt-1 text-sm text-ink-500">
            Everything I can do — schemas, permission levels, and recent usage.
          </p>
        </div>
        <button
          onClick={load}
          className="focus-ring rounded-lg border border-ink-200 bg-ink-100 px-3.5 py-2 text-xs font-medium text-ink-400 transition-colors hover:bg-ink-200"
        >
          ↻ Refresh
        </button>
      </header>

      {error ? (
        <div className="mt-5">
          <ErrorBox message={error} onRetry={load} />
        </div>
      ) : null}

      <section className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Tool list */}
        <div className="panel flex min-h-[24rem] flex-col p-4 lg:col-span-1">
          <div className="mb-3 flex items-center justify-between px-1">
            <span className="hud-label">Available tools</span>
            <span className="data-mono text-[10px] text-ink-400">
              {tools ? tools.length : '—'}
            </span>
          </div>
          {loading && !tools ? (
            <LoadingSpinner label="Loading tools" />
          ) : !tools || tools.length === 0 ? (
            <EmptyState
              icon="✦"
              title="No tools registered"
              hint="The tool registry is empty. Check backend discovery."
            />
          ) : (
            <div className="flex flex-col gap-1.5">
              {tools.map((t) => (
                <ToolListItem
                  key={t.name}
                  tool={t}
                  active={selected === t.name}
                  onClick={() => setSelected(t.name)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Tool detail */}
        <div className="lg:col-span-2">
          {selected ? (
            <ToolDetail name={selected} onError={(m) => pushToast('fail', m)} />
          ) : (
            <div className="panel">
              <EmptyState
                icon="✦"
                title="No tool selected"
                hint="Pick a tool from the list to inspect its schema and recent activity."
              />
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function ToolListItem({
  tool,
  active,
  onClick,
}: {
  tool: ToolSchema
  active: boolean
  onClick: () => void
}) {
  const tone = PERMISSION_TONE[tool.permission] ?? 'idle'
  return (
    <button
      onClick={onClick}
      className={`focus-ring group flex flex-col gap-1.5 rounded-xl border px-3.5 py-3 text-left transition-all ${
        active
          ? 'border-sig-500/40 bg-sig-50 shadow-soft'
          : 'border-ink-200 bg-ink-100 hover:border-ink-300 hover:bg-ink-200'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs font-medium text-ink-800">{tool.name}</span>
        <span
          className={`rounded-full border px-1.5 py-px text-[9px] font-medium uppercase tracking-wide ${
            tone === 'ok'
              ? 'border-ok-500/30 text-ok-600 bg-ok-500/8'
              : tone === 'warn'
              ? 'border-warn-500/40 text-warn-600 bg-warn-500/8'
              : 'border-bad-500/40 text-bad-600 bg-bad-500/8'
          }`}
        >
          {tool.permission}
        </span>
      </div>
      <p className="line-clamp-2 text-[11px] leading-relaxed text-ink-500">{tool.description}</p>
    </button>
  )
}

function ToolDetail({ name, onError }: { name: string; onError: (msg: string) => void }) {
  const [tool, setTool] = useState<ToolSchema | null>(null)
  const [recent, setRecent] = useState<ToolInvocation[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingRecent, setLoadingRecent] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setTool(null)
    setRecent([])
    Promise.all([api.getTool(name), api.recentToolInvocations(name, 15)])
      .then(([t, r]) => {
        if (cancelled) return
        setTool(t)
        setRecent(r.invocations)
      })
      .catch((e) => {
        if (cancelled) return
        const msg = e instanceof ApiError ? e.message : String(e)
        onError(msg)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [name, onError])

  async function refreshRecent() {
    setLoadingRecent(true)
    try {
      const r = await api.recentToolInvocations(name, 15)
      setRecent(r.invocations)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e)
      onError(msg)
    } finally {
      setLoadingRecent(false)
    }
  }

  if (loading) {
    return (
      <div className="panel">
        <LoadingSpinner label={`Loading ${name}`} />
      </div>
    )
  }
  if (!tool) {
    return (
      <div className="panel">
        <EmptyState icon="?" title="Tool not found" hint={`No tool named ${name}`} />
      </div>
    )
  }

  const params = tool.parameters?.properties ?? {}
  const required = new Set(tool.parameters?.required ?? [])

  return (
    <div className="flex flex-col gap-4">
      {/* Header card */}
      <div className="panel p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <h2 className="font-mono text-lg font-medium text-ink-900">{tool.name}</h2>
              <StatusBadge
                tone={PERMISSION_TONE[tool.permission] ?? 'idle'}
                label={tool.permission}
              />
            </div>
            <p className="mt-2 text-sm leading-relaxed text-ink-600">{tool.description}</p>
            <p className="mt-1.5 text-[11px] text-ink-400">
              {PERMISSION_NOTE[tool.permission] ?? ''}
            </p>
          </div>
        </div>
      </div>

      {/* Schema */}
      <div className="panel p-5">
        <div className="mb-3.5 flex items-center justify-between">
          <span className="hud-label">Parameters</span>
          <span className="data-mono text-[10px] text-ink-400">
            {Object.keys(params).length} input{Object.keys(params).length === 1 ? '' : 's'}
          </span>
        </div>
        {Object.keys(params).length === 0 ? (
          <p className="text-sm text-ink-400">
            No parameters — runs with default inputs.
          </p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {Object.entries(params).map(([pname, pschema]) => (
              <SchemaRow
                key={pname}
                name={pname}
                schema={pschema}
                required={required.has(pname)}
                expanded={expanded === pname}
                onToggle={() => setExpanded(expanded === pname ? null : pname)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Recent invocations */}
      <div className="panel p-5">
        <div className="mb-3.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="hud-label">Recent usage</span>
            <span className="data-mono text-[10px] text-ink-400">{recent.length}</span>
          </div>
          <Button variant="ghost" size="sm" onClick={refreshRecent} disabled={loadingRecent}>
            {loadingRecent ? 'Refreshing…' : '↻ Refresh'}
          </Button>
        </div>
        {recent.length === 0 ? (
          <EmptyState
            icon="✦"
            title="No usage recorded yet"
            hint="I haven't called this tool yet, or the log was cleared."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full table-fixed border-collapse text-left">
              <colgroup>
                <col className="w-[18ch]" />
                <col className="w-[10ch]" />
                <col className="w-[8ch]" />
                <col className="w-[10ch]" />
                <col />
              </colgroup>
              <thead>
                <tr className="hud-label border-b border-ink-200/70">
                  <th className="py-2.5 pr-3 font-medium">When</th>
                  <th className="py-2.5 pr-3 font-medium">Task</th>
                  <th className="py-2.5 pr-3 font-medium">Status</th>
                  <th className="py-2.5 pr-3 text-right font-medium">Duration</th>
                  <th className="py-2.5 pr-3 font-medium">Error</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((inv, i) => (
                  <tr
                    key={`${inv.timestamp}-${i}`}
                    className="border-b border-ink-100 text-xs transition-colors hover:bg-ink-100/50"
                  >
                    <td className="py-2.5 pr-3 data-mono text-ink-500">
                      {fmtClock(inv.timestamp)}
                      <span className="ml-1.5 text-[10px] text-ink-400">
                        {fmtRelative(inv.timestamp)}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 data-mono text-ink-600">
                      {inv.task_public_id ? inv.task_public_id.slice(0, 8) : '—'}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={`font-mono text-[11px] font-medium ${
                          inv.ok ? 'text-ok-600' : 'text-bad-600'
                        }`}
                      >
                        {inv.ok ? '✓ ok' : '✕ fail'}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-right data-mono text-ink-500">
                      {fmtMs(inv.duration_ms)}
                    </td>
                    <td className="py-2.5 pr-3 truncate text-[11px] text-bad-600/80" title={inv.error ?? ''}>
                      {inv.error ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function SchemaRow({
  name,
  schema,
  required,
  expanded,
  onToggle,
}: {
  name: string
  schema: Record<string, unknown>
  required: boolean
  expanded: boolean
  onToggle: () => void
}) {
  const typeStr = (schema.type as string) ?? (schema.anyOf ? 'union' : 'any')
  const desc = (schema.description as string) ?? ''
  const enumVals = Array.isArray(schema.enum) ? (schema.enum as string[]) : null
  const hasDetail = !!desc || !!enumVals || Object.keys(schema).length > 3
  return (
    <div className="rounded-lg border border-ink-200/70 bg-ink-100/40">
      <button
        onClick={hasDetail ? onToggle : undefined}
        className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left ${
          hasDetail ? 'hover:bg-ink-100/60' : 'cursor-default'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-[11px] text-sig-700">{name}</span>
          {required ? (
            <span className="rounded-full border border-warn-500/40 bg-warn-500/10 px-1.5 text-[9px] font-medium uppercase text-warn-600">
              required
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-ink-500">{typeStr}</span>
          {hasDetail ? (
            <span className="text-ink-400 text-[10px]">{expanded ? '▾' : '▸'}</span>
          ) : null}
        </div>
      </button>
      {expanded && hasDetail ? (
        <div className="border-t border-ink-200/70 px-3 py-2.5 text-[11px] leading-relaxed text-ink-600">
          {desc ? <p className="mb-1.5">{desc}</p> : null}
          {enumVals ? (
            <div className="mb-1.5">
              <span className="hud-label mr-1">enum</span>
              <span className="text-wrap-safe font-mono text-ink-600">
                {enumVals.join(' | ')}
              </span>
            </div>
          ) : null}
          <details className="mt-1">
            <summary className="cursor-pointer font-mono text-[10px] text-ink-400 hover:text-ink-600">
              raw schema
            </summary>
            <pre className="mt-1.5 max-h-40 overflow-auto rounded-md bg-ink-100 p-2 font-mono text-[10px] text-ink-500">
              {JSON.stringify(schema, null, 2)}
            </pre>
          </details>
        </div>
      ) : null}
    </div>
  )
}
