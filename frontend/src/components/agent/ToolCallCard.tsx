import { useState } from 'react'
import type { ToolCall } from '../../lib/execution'
import { fmtMs } from '../../lib/format'

/**
 * Card showing one tool invocation: name, arguments (expandable), and result
 * status with output preview. Pairs tool.request + tool.result events.
 */
export function ToolCallCard({ call }: { call: ToolCall }) {
  const [expanded, setExpanded] = useState(false)
  const hasResult = !!call.result
  const argKeys = Object.keys(call.arguments)

  return (
    <div className="rounded-xl border border-ink-200/70 bg-ink-50/50 p-3 transition-shadow hover:shadow-soft">
      <div className="flex items-center gap-2.5">
        <span
          className={`flex h-6 w-6 items-center justify-center rounded-lg font-mono text-[11px] ${
            !hasResult
              ? 'bg-sig-500/15 text-sig-600 animate-pulseDot'
              : call.result?.ok
              ? 'bg-ok-500/15 text-ok-600'
              : 'bg-bad-500/15 text-bad-600'
          }`}
        >
          ⚙
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-medium text-ink-800">{call.tool}</span>
            <span className="font-mono text-[10px] text-ink-400">
              iter {call.iteration || '—'}
            </span>
          </div>
        </div>
        {hasResult ? (
          <div className="flex items-center gap-2">
            <span
              className={`font-mono text-[10px] font-medium ${
                call.result?.ok ? 'text-ok-600' : 'text-bad-600'
              }`}
            >
              {call.result?.ok ? '✓ ok' : '✕ fail'}
            </span>
            <span className="data-mono text-[10px] text-ink-400">
              {fmtMs(call.result?.duration_ms ?? 0)}
            </span>
          </div>
        ) : (
          <span className="font-mono text-[10px] text-sig-600 animate-pulseDot">running…</span>
        )}
      </div>

      {/* Arguments */}
      {argKeys.length > 0 ? (
        <div className="mt-2.5">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-ink-400 transition-colors hover:text-ink-700"
          >
            <span>{expanded ? '▾' : '▸'}</span>
            <span className="hud-label">inputs</span>
            <span className="text-ink-300">({argKeys.length})</span>
          </button>
          {expanded ? (
            <pre className="mt-1.5 max-h-40 overflow-auto rounded-md bg-ink-100 p-2 font-mono text-[10px] text-ink-600">
              {JSON.stringify(call.arguments, null, 2)}
            </pre>
          ) : (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {argKeys.slice(0, 4).map((k) => (
                <span
                  key={k}
                  className="rounded-md border border-ink-200 bg-ink-100 px-1.5 py-0.5 font-mono text-[10px] text-ink-500"
                >
                  {k}
                </span>
              ))}
              {argKeys.length > 4 ? (
                <span className="font-mono text-[10px] text-ink-400">
                  +{argKeys.length - 4}
                </span>
              ) : null}
            </div>
          )}
        </div>
      ) : null}

      {/* Result preview */}
      {hasResult && call.result?.output_preview ? (
        <div className="mt-2.5">
          <div className="hud-label mb-1.5">output</div>
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md bg-ink-100 p-2 font-mono text-[10px] text-ink-600">
            {call.result.output_preview}
          </pre>
        </div>
      ) : null}

      {hasResult && !call.result?.ok && call.result?.output_preview ? (
        <div className="mt-1.5 text-[10px] text-bad-600">tool failed — see output above</div>
      ) : null}
    </div>
  )
}
