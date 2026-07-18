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
      className="focus-ring group block rounded-xl border border-ink-200/70 bg-ink-100 p-3.5 transition-all hover:-translate-y-0.5 hover:border-sig-500/30 hover:shadow-card"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="data-mono text-[10px] text-ink-400">
              #{shortId(task.public_id)}
            </span>
            <span
              className={`rounded-full border px-1.5 py-px font-mono text-[9px] font-medium uppercase ${
                task.mode === 'plan'
                  ? 'text-violet-600 border-violet-500/30 bg-violet-500/8'
                  : 'text-sig-600 border-sig-500/30 bg-sig-50'
              }`}
            >
              {task.mode}
            </span>
            <StatusBadge status={task.status} pulse={active} />
          </div>
          <p className="mt-2 truncate text-sm leading-snug text-ink-700 group-hover:text-sig-700">
            {task.request || '(empty request)'}
          </p>
        </div>
        <span className="shrink-0 pt-0.5 text-[10px] text-ink-400">
          {fmtRelative(task.updated_at ?? task.created_at)}
        </span>
      </div>
      {showProgress ? (
        <div className="mt-3">
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
