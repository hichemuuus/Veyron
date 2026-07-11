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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/70 p-4 backdrop-blur-sm">
      <div className="panel w-full max-w-md animate-riseIn p-5 shadow-glow">
        <div className="flex items-center gap-2">
          <span className="text-warn-400">🔒</span>
          <span className="hud-label text-warn-400">APPROVAL REQUIRED</span>
          <span
            className={`ml-auto rounded border px-1.5 py-0.5 font-mono text-[10px] ${
              isRestricted
                ? 'border-bad-500/40 text-bad-400'
                : 'border-warn-500/40 text-warn-400'
            }`}
          >
            {conf.permission}
          </span>
        </div>

        <h3 className="mt-3 text-sm font-semibold text-gray-100">{conf.summary}</h3>

        <dl className="mt-3 space-y-1 font-mono text-[11px] text-ink-300">
          <div className="flex justify-between gap-3">
            <dt className="text-ink-400">tool</dt>
            <dd className="text-sig-300">{conf.tool}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-ink-400">task</dt>
            <dd className="truncate text-ink-300">{conf.topic.slice(0, 12)}…</dd>
          </div>
        </dl>

        {Object.keys(conf.inputs).length > 0 ? (
          <pre className="mt-3 max-h-40 overflow-auto rounded-md border border-ink-700/60 bg-ink-900/70 p-2 font-mono text-[11px] text-ink-300">
            {JSON.stringify(conf.inputs, null, 2)}
          </pre>
        ) : null}

        {isRestricted ? (
          <div className="mt-3">
            <label className="hud-label">REASON (required)</label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this action authorized?"
              className="focus-ring mt-1 w-full rounded-md border border-ink-700/70 bg-ink-900/70 px-2.5 py-1.5 text-xs text-gray-100 placeholder:text-ink-500"
            />
          </div>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="danger" onClick={() => respond(false)} disabled={busy}>
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
