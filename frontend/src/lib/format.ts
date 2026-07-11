/**
 * Formatting + classification helpers shared across the UI.
 */

import type { TaskStatus } from '../api/types'

export function fmtBytes(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return '—'
  let x = Number(n)
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  for (const u of units) {
    if (Math.abs(x) < 1024) return `${x.toFixed(x < 10 && u !== 'B' ? 1 : 0)}${u}`
    x /= 1024
  }
  return `${x.toFixed(1)}EB`
}

export function fmtPct(n: number | undefined | null, digits = 0): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `${Number(n).toFixed(digits)}%`
}

export function fmtMs(ms: number | undefined | null): string {
  if (ms == null || ms <= 0) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`
  const m = Math.floor(s / 60)
  const rem = Math.round(s % 60)
  return `${m}m ${rem}s`
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Date.now() - then
  const abs = Math.abs(diff)
  const future = diff < 0
  const mins = abs / 60000
  if (abs < 5000) return 'just now'
  if (abs < 60000) return `${future ? 'in ' : ''}${Math.round(abs / 1000)}s${future ? '' : ' ago'}`
  if (mins < 60) return `${future ? 'in ' : ''}${Math.round(mins)}m${future ? '' : ' ago'}`
  const hrs = mins / 60
  if (hrs < 24) return `${future ? 'in ' : ''}${Math.round(hrs)}h${future ? '' : ' ago'}`
  const days = hrs / 24
  if (days < 7) return `${future ? 'in ' : ''}${Math.round(days)}d${future ? '' : ' ago'}`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function fmtTimeFromTs(ts: number | null | undefined): string {
  if (ts == null) return '—'
  // Backend event ts is loop.time() (monotonic relative) — show as HH:MM:SS of
  // wall clock when received. We treat it as ms-since-epoch-ish fallback.
  const d = new Date(ts * 1000)
  if (Number.isNaN(d.getTime())) {
    return new Date().toLocaleTimeString(undefined, { hour12: false })
  }
  return d.toLocaleTimeString(undefined, { hour12: false })
}

export function shortId(id: string | null | undefined, len = 8): string {
  if (!id) return '—'
  return id.length <= len ? id : `${id.slice(0, len)}`
}

// ── Status classification ───────────────────────────────────────────────

export type StatusTone = 'active' | 'ok' | 'warn' | 'fail' | 'idle'

export interface StatusInfo {
  label: string
  tone: StatusTone
}

const STATUS_MAP: Record<string, StatusInfo> = {
  created: { label: 'Queued', tone: 'idle' },
  planning: { label: 'Planning', tone: 'active' },
  running: { label: 'Running', tone: 'active' },
  paused: { label: 'Paused', tone: 'warn' },
  verifying: { label: 'Verifying', tone: 'active' },
  completed: { label: 'Completed', tone: 'ok' },
  failed: { label: 'Failed', tone: 'fail' },
  cancelled: { label: 'Cancelled', tone: 'warn' },
}

export function statusInfo(status: string | undefined | null): StatusInfo {
  if (!status) return { label: 'Unknown', tone: 'idle' }
  return STATUS_MAP[status] ?? { label: status, tone: 'idle' }
}

export function isActiveStatus(status: string | undefined | null): boolean {
  const t = statusInfo(status).tone
  return t === 'active'
}

export function isTerminalStatus(status: string | undefined | null): boolean {
  return ['completed', 'failed', 'cancelled'].includes(status ?? '')
}

export const TONE_RING: Record<StatusTone, string> = {
  active: 'border-sig-400/40 text-sig-300 bg-sig-500/10',
  ok: 'border-ok-500/40 text-ok-400 bg-ok-500/10',
  warn: 'border-warn-500/40 text-warn-400 bg-warn-500/10',
  fail: 'border-bad-500/40 text-bad-400 bg-bad-500/10',
  idle: 'border-ink-600/60 text-ink-400 bg-ink-700/30',
}

export const TONE_DOT: Record<StatusTone, string> = {
  active: 'bg-sig-400',
  ok: 'bg-ok-500',
  warn: 'bg-warn-500',
  fail: 'bg-bad-500',
  idle: 'bg-ink-500',
}

export const TASK_STATUS_VALUES: TaskStatus[] = [
  'created',
  'planning',
  'running',
  'paused',
  'verifying',
  'completed',
  'failed',
  'cancelled',
]
