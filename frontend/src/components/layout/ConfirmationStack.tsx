import { useState } from 'react'
import { useAppStore } from '../../stores/appStore'
import { getWsClient } from '../../api/websocket'
import { Button } from '../ui'

/**
 * Modal stack for pending security confirmations emitted by the backend
 * (security.confirm events). The user approves/denies; we reply over the
 * WebSocket via confirm.respond. RESTRICTED actions require a reason.
 */
export function ConfirmationStack() {
  const confirmations = useAppStore((s) => s.confirmations)
  if (confirmations.length === 0) return null
  const top = confirmations[0]
  return <ConfirmationDialog key={top.confirmation_id} conf={top} />
}

function ConfirmationDialog({
  conf,
}: {
  conf: ReturnType<typeof useAppStore.getState>['confirmations'][number]
}) {
  const pushToast = useAppStore((s) => s.pushToast)
  const isRestricted = conf.permission === 'RESTRICTED'
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const respond = (approved: boolean) => {
    if (approved && isRestricted && !reason.trim()) {
      pushToast('warn', 'A reason is required to approve restricted actions.')
      return
    }
    setBusy(true)
    getWsClient().send({
      type: 'confirm.respond',
      confirmation_id: conf.confirmation_id,
      approved,
      reason: approved && isRestricted ? reason.trim() : null,
    })
    // Optimistically close; store resolves on security.confirm.resolved event,
    // but also resolve after a beat in case the event is missed.
    window.setTimeout(() => setBusy(false), 600)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/30 p-4 backdrop-blur-sm">
      <div className="panel w-full max-w-md animate-riseIn p-6 shadow-card-lg">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-warn-500/15 text-warn-500">
            !
          </span>
          <span className="hud-label text-warn-600">Approval needed</span>
          <span
            className={`ml-auto rounded-full border px-2 py-0.5 font-mono text-[10px] font-medium ${
              isRestricted
                ? 'border-bad-500/40 bg-bad-500/10 text-bad-600'
                : 'border-warn-500/40 bg-warn-500/10 text-warn-600'
            }`}
          >
            {conf.permission}
          </span>
        </div>

        <h3 className="text-wrap-safe mt-4 font-display text-lg font-medium text-ink-900">{conf.summary}</h3>

        <dl className="mt-4 space-y-1.5 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Tool</dt>
            <dd className="font-mono text-sig-700">{conf.tool}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-ink-500">Task</dt>
            <dd className="truncate font-mono text-ink-600">{conf.topic.slice(0, 12)}…</dd>
          </div>
        </dl>

        {Object.keys(conf.inputs).length > 0 ? (
          <pre className="mt-4 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-ink-200 bg-ink-100 p-2.5 font-mono text-[11px] text-ink-600">
            {JSON.stringify(conf.inputs, null, 2)}
          </pre>
        ) : null}

        {isRestricted ? (
          <div className="mt-4">
            <label className="hud-label">Reason (required)</label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this action authorized?"
              className="focus-ring mt-1.5 w-full rounded-lg border border-ink-200 bg-ink-100 px-3 py-2 text-sm text-ink-900 placeholder:text-ink-400"
            />
          </div>
        ) : null}

        <div className="mt-6 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={() => respond(false)} disabled={busy}>
            Deny
          </Button>
          <Button variant="primary" onClick={() => respond(true)} disabled={busy}>
            {busy ? 'Sending…' : 'Approve'}
          </Button>
        </div>
      </div>
    </div>
  )
}
