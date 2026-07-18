import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ProjectAnalysis, ProjectIssue, ProjectTreeNode } from '../api/types'
import {
  ErrorBox,
  EmptyState,
  Button,
} from '../components/ui'
import { StatusBadge } from '../components/ui/StatusBadge'
import { fmtBytes } from '../lib/format'

const SEVERITY_TONE: Record<string, 'ok' | 'warn' | 'fail' | 'idle'> = {
  low: 'idle',
  info: 'idle',
  medium: 'warn',
  high: 'fail',
}

const SEVERITY_GLYPH: Record<string, string> = {
  low: '·',
  info: 'i',
  medium: '!',
  high: '✕',
}

const MAX_DEPTH_DEFAULT = 5

export function ProjectIntelligencePage() {
  const [path, setPath] = useState('')
  const [maxDepth, setMaxDepth] = useState(MAX_DEPTH_DEFAULT)
  const [includeHidden, setIncludeHidden] = useState(false)
  const [analysis, setAnalysis] = useState<ProjectAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scanProgress, setScanProgress] = useState(0)

  async function analyze() {
    const trimmed = path.trim()
    if (!trimmed) return
    setLoading(true)
    setError(null)
    setAnalysis(null)
    setScanProgress(0)

    // Simulated scan progress — the endpoint is synchronous, but we animate
    // the scan bar so the user sees motion while the request is in flight.
    const progTimer = window.setInterval(() => {
      setScanProgress((p) => (p >= 92 ? p : p + Math.random() * 14))
    }, 250)

    try {
      const result = await api.analyzeProject({
        path: trimmed,
        max_depth: maxDepth,
        include_hidden: includeHidden,
      })
      setScanProgress(100)
      setAnalysis(result)
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      window.clearInterval(progTimer)
      setLoading(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      analyze()
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-8 page-enter">
      {/* Breadcrumb-style header — show path when scanned */}
      <header className="flex items-end justify-between">
        <div className="min-w-0">
          {analysis ? (
            <div className="flex items-center gap-2 truncate">
              <span className="hud-label text-ink-500">Project</span>
              <span className="font-mono text-[11px] text-ink-600">/</span>
              <span className="truncate font-mono text-sm font-medium text-ink-900">
                {analysis.root}
              </span>
            </div>
          ) : (
            <>
              <h1 className="font-display text-display-sm font-medium text-ink-900">Projects</h1>
              <p className="mt-1 text-sm text-ink-500">
                Point me at a directory and I'll map its stack, structure, and health.
              </p>
            </>
          )}
        </div>
      </header>

      {/* Scan form */}
      <section className="panel mt-6 p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[12px] font-medium uppercase tracking-[0.12em] text-ink-800">Project path</span>
          <span className="font-mono text-[10px] text-ink-400">
            sandbox-validated · ⌘↵ to scan
          </span>
        </div>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="/path/to/project (within sandbox roots)"
            className="focus-ring h-11 flex-1 rounded-lg border border-ink-200 bg-ink-100/50 px-3.5 font-mono text-sm text-ink-900 placeholder:text-ink-400"
          />
          <div className="flex items-center gap-2 rounded-lg border border-ink-200/70 bg-ink-100/30 px-3 py-2">
            <label className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500">
              depth
              <input
                type="number"
                min={1}
                max={20}
                value={maxDepth}
                onChange={(e) => setMaxDepth(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                className="focus-ring w-14 rounded-lg border border-ink-200 bg-ink-100/50 px-2 py-1.5 text-center text-xs text-ink-800"
              />
            </label>
            <span className="h-4 w-px bg-ink-200/60" />
            <label className="flex items-center gap-1.5 text-[11px] font-medium text-ink-500">
              <input
                type="checkbox"
                checked={includeHidden}
                onChange={(e) => setIncludeHidden(e.target.checked)}
                className="accent-sig-500"
              />
              hidden
            </label>
            <span className="h-4 w-px bg-ink-200/60" />
            <Button
              variant="primary"
              onClick={analyze}
              disabled={loading || !path.trim()}
            >
              {loading ? 'Scanning…' : 'Scan →'}
            </Button>
          </div>
        </div>

        {/* Scan progress bar */}
        {loading ? (
          <div className="mt-4">
            <div className="scanbar h-1.5 w-full overflow-hidden rounded-full bg-ink-200">
              <div
                className="h-full bg-sig-500 transition-all duration-300"
                style={{ width: `${scanProgress}%` }}
              />
            </div>
            <div className="mt-2 flex justify-between font-mono text-[10px] text-ink-400">
              <span>analyzing structure · detecting stack · parsing dependencies</span>
              <span>{Math.round(scanProgress)}%</span>
            </div>
          </div>
        ) : null}
      </section>

      {error ? (
        <div className="mt-5">
          <ErrorBox message={error} />
        </div>
      ) : null}

      {!loading && !analysis && !error ? (
        <div className="panel mt-5">
          <EmptyState
            icon="✦"
            title="No project scanned yet"
            hint="Enter a project path above to analyze its structure, technologies, and issues."
          />
        </div>
      ) : null}

      {analysis ? <AnalysisResult analysis={analysis} /> : null}
    </div>
  )
}

function AnalysisResult({ analysis }: { analysis: ProjectAnalysis }) {
  return (
    <div className="mt-6 flex flex-col gap-5">
      {/* Summary stats */}
      <section className="grid grid-cols-1 gap-3 md:grid-cols-5">
        {/* Issues — prominent, accent-colored */}
        <div className="panel relative overflow-hidden border-l-2 transition-shadow hover:shadow-card-lg md:col-span-2"
          style={{
            borderLeftColor: analysis.issues.filter((i) => i.severity === 'high').length > 0
              ? 'var(--status-warning)' : 'var(--status-online)'
          }}
        >
          <span className="hud-label">Issues</span>
          <span className="mt-2 block font-display text-4xl font-medium leading-none tracking-tight text-warn-500">
            {analysis.issues.length}
          </span>
          {analysis.issues.length > 0 ? (
            <span className="mt-1.5 block text-[11px] text-ink-500">
              {analysis.issues.filter((i) => i.severity === 'high').length} high
            </span>
          ) : null}
        </div>

        {/* Secondary stats — smaller, lower-weight */}
        <div className="grid grid-cols-3 gap-3 md:col-span-3">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-shadow hover:shadow-card-lg">
            <span className="hud-label">Files</span>
            <span className="mt-1.5 block font-display text-xl font-medium leading-none tracking-tight text-ink-800">
              {analysis.file_count.toLocaleString()}
            </span>
          </div>
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-shadow hover:shadow-card-lg">
            <span className="hud-label">Technologies</span>
            <span className="mt-1.5 block font-display text-xl font-medium leading-none tracking-tight text-ink-800">
              {analysis.technologies.length}
            </span>
          </div>
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-shadow hover:shadow-card-lg">
            <span className="hud-label">Suggestions</span>
            <span className="mt-1.5 block font-display text-xl font-medium leading-none tracking-tight text-ink-800">
              {analysis.recommendations.length}
            </span>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Technologies */}
        <div className="panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-900">Detected stack</span>
            <span className="data-mono text-[10px] text-ink-400">
              {analysis.technologies.length} tech
            </span>
          </div>
          {analysis.technologies.length === 0 ? (
            <p className="text-sm text-ink-400">
              No technologies detected.
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {analysis.technologies.map((tech, idx) => (
                <div
                  key={tech.name}
                  className="rounded-xl border border-ink-200/70 bg-ink-100/50 p-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium text-sig-700">
                      {tech.name}
                    </span>
                    <span className="data-mono text-[10px] text-ink-500">
                      {(tech.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="mt-1.5 h-0.5 w-full overflow-hidden rounded-full bg-ink-200">
                    <div
                      className={`h-full rounded-full ${idx < 2 ? 'bg-sig-500' : 'bg-ink-400'}`}
                      style={{ width: `${Math.max(4, tech.confidence * 100)}%` }}
                    />
                  </div>
                  {tech.evidence.length > 0 ? (
                    <p className="mt-2 truncate font-mono text-[10px] text-ink-400">
                      {tech.evidence.join(' · ')}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Dependencies */}
        <div className="panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-900">Dependencies</span>
            <span className="data-mono text-[10px] text-ink-400">
              {Object.keys(analysis.dependencies).length} manager(s)
            </span>
          </div>
          {Object.keys(analysis.dependencies).length === 0 ? (
            <p className="text-sm text-ink-400">
              No dependency files detected.
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {Object.entries(analysis.dependencies).map(([mgr, deps]) => (
                <DependencyGroup key={mgr} manager={mgr} deps={deps} />
              ))}
            </div>
          )}
        </div>

        {/* Issues */}
        <div className="panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-900">Issues found</span>
            <span className="data-mono text-[10px] text-ink-400">
              {analysis.issues.length} total
            </span>
          </div>
          {analysis.issues.length === 0 ? (
            <EmptyState icon="✓" title="No issues found" hint="This project looks clean." />
          ) : (
            <div className="flex flex-col gap-2">
              {analysis.issues.map((issue, i) => (
                <IssueRow key={i} issue={issue} />
              ))}
            </div>
          )}
        </div>

        {/* Recommendations */}
        <div className="panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-900">Suggestions</span>
            <span className="data-mono text-[10px] text-ink-400">
              {analysis.recommendations.length} tip{analysis.recommendations.length === 1 ? '' : 's'}
            </span>
          </div>
          {analysis.recommendations.length === 0 ? (
            <EmptyState icon="✓" title="No suggestions" hint="Nothing to flag." />
          ) : (
            <ul className="flex flex-col gap-2">
              {analysis.recommendations.map((rec, i) => (
                <li
                  key={i}
                  className="flex gap-2.5 rounded-xl border border-ink-200/70 bg-ink-100/50 p-3 text-xs leading-relaxed text-ink-700"
                >
                  <span className="text-sig-500">→</span>
                  <span>{rec}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Structure tree */}
      <div className="panel p-5">
        <div className="mb-4 flex items-center justify-between">
          <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-900">Project structure</span>
          <span className="data-mono text-[10px] text-ink-400">
            root: {analysis.root}
          </span>
        </div>
        <div className="overflow-x-auto">
          <TreeView node={analysis.structure} depth={0} />
        </div>
      </div>
    </div>
  )
}

function DependencyGroup({ manager, deps }: { manager: string; deps: string[] }) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? deps : deps.slice(0, 8)
  return (
    <div className="rounded-xl border border-ink-200/70 bg-ink-100/50 p-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between"
      >
        <span className="text-[11px] font-medium uppercase tracking-wide text-violet-600">
          {manager}
        </span>
        <span className="data-mono text-[10px] text-ink-400">
          {deps.length} pkg{deps.length === 1 ? '' : 's'} {expanded ? '▾' : '▸'}
        </span>
      </button>
      <div className={`mt-2.5 flex flex-wrap gap-1 ${!expanded ? 'max-h-[108px] overflow-hidden' : ''}`}>
        {visible.map((d) => (
          <span
            key={d}
            className="rounded-md border border-ink-200 bg-ink-100 px-1.5 py-0.5 font-mono text-[10px] text-ink-600"
          >
            {d}
          </span>
        ))}
        {deps.length > 8 && !expanded ? (
          <button
            onClick={() => setExpanded(true)}
            className="text-[10px] font-medium text-sig-600 hover:underline"
          >
            +{deps.length - 8} more
          </button>
        ) : null}
      </div>
    </div>
  )
}

function IssueRow({ issue }: { issue: ProjectIssue }) {
  const tone = SEVERITY_TONE[issue.severity] ?? 'idle'
  const glyph = SEVERITY_GLYPH[issue.severity] ?? '·'
  return (
    <div className="flex items-start gap-3 rounded-xl border border-ink-200/70 bg-ink-100/50 p-3">
      <span
        className={`mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[11px] font-medium ${
          tone === 'fail'
            ? 'bg-bad-500/15 text-bad-600'
            : tone === 'warn'
            ? 'bg-warn-500/15 text-warn-600'
            : 'bg-ink-200 text-ink-500'
        }`}
      >
        {glyph}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] uppercase tracking-wide text-ink-400">
            {issue.category}
          </span>
          <StatusBadge tone={tone} label={issue.severity} />
        </div>
        <p className="text-wrap-safe mt-1 text-xs leading-relaxed text-ink-700">{issue.message}</p>
      </div>
    </div>
  )
}

function TreeView({ node, depth }: { node: ProjectTreeNode; depth: number }) {
  const [expanded, setExpanded] = useState(depth < 2)
  const isDir = node.type === 'dir'
  return (
    <div>
      <button
        onClick={isDir ? () => setExpanded((v) => !v) : undefined}
        className={`flex items-center gap-1.5 py-0.5 font-mono text-[11px] ${
          isDir ? 'cursor-pointer hover:text-ink-900' : 'cursor-default'
        }`}
        style={{ paddingLeft: `${depth * 16}px` }}
      >
        {isDir ? (
          <span className="text-ink-400">{expanded ? '▾' : '▸'}</span>
        ) : (
          <span className="text-ink-300">·</span>
        )}
        <span className={`truncate ${isDir ? 'font-medium text-sig-700' : 'text-ink-600'}`}>{node.name}</span>
        {!isDir && typeof node.size === 'number' ? (
          <span className="text-[10px] text-ink-400">{fmtBytes(node.size)}</span>
        ) : null}
      </button>
      {isDir && expanded && node.children ? (
        <div>
          {node.children.map((child, i) => (
            <TreeView key={`${child.name}-${i}`} node={child} depth={depth + 1} />
          ))}
        </div>
      ) : null}
    </div>
  )
}
