import { Link } from 'react-router-dom'
import type { TaskBrief } from '../../api/types'
import { StatusBadge, ProgressMeter } from '../ui'
import { fmtRelative, shortId, isActiveStatus } from '../../lib/format'

interface TaskRowProps {
  task: TaskBrief
  showProgress?: boolean
}

/**
 * Compact, clickable task summary used in lists. Links to the task detail page.
 */
export function TaskRow({ task, showProgress = true }: TaskRowProps) {
  const active = isActiveStatus(task.status)
  const pct = task.progress?.percent ?? 0
  return (
    <Link
      to={`/agent/${task.public_id}`}
      className="focus-ring group block rounded-lg border border-ink-800/60 bg-ink-900/40 p-3 transition-colors hover:border-sig-400/30 hover:bg-ink-850/60"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="data-mono text-[10px] text-ink-500">
              #{shortId(task.public_id)}
            </span>
            <span
              className={`rounded border border-ink-700/60 px-1 py-px font-mono text-[9px] uppercase ${
                task.mode === 'plan' ? 'text-violet-400' : 'text-sig-400'
              }`}
            >
              {task.mode}
            </span>
            <StatusBadge status={task.status} pulse={active} />
          </div>
          <p className="mt-1.5 truncate text-sm text-gray-200 group-hover:text-sig-200">
            {task.request || '(empty request)'}
          </p>
        </div>
        <span className="shrink-0 pt-0.5 font-mono text-[10px] text-ink-500">
          {fmtRelative(task.updated_at ?? task.created_at)}
        </span>
      </div>
      {showProgress ? (
        <div className="mt-2.5">
          <ProgressMeter
            percent={pct}
            completed={task.progress?.completed_steps}
            total={task.progress?.total_steps}
            active={active}
            compact
          />
        </div>
      ) : null}
    </Link>
  )
}
