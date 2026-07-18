import { useEffect, useState, useCallback, type ReactNode } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { useAppStore } from '../stores/appStore'
import { useUpdateStore } from '../stores/updateStore'
import { getLastRequestMetrics, getRequestHistory, api } from '../api/client'
import { getWsClient } from '../api/websocket'
import { getLastHealthCheckError } from '../hooks/useWebSocket'

interface BackendInfo {
  version: string
  pid: number
  tools: string[]
  sandbox_roots: string[]
  model: {
    base_model: string
    ollama_url: string
    provider: string
    remote_enabled: boolean
  }
}

interface SectionLoadState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

function statusText(status: number | null): string {
  if (status == null) return 'timeout'
  if (status >= 200 && status < 300) return String(status)
  if (status >= 300 && status < 400) return String(status)
  if (status >= 400) return `${status} ${statusMessage(status)}`
  return String(status)
}

function statusMessage(status: number): string {
  const messages: Record<number, string> = {
    200: 'OK',
    201: 'Created',
    204: 'No Content',
    301: 'Moved Permanently',
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    408: 'Request Timeout',
    409: 'Conflict',
    422: 'Unprocessable Entity',
    429: 'Too Many Requests',
    500: 'Internal Server Error',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
  }
  return messages[status] ?? ''
}

function updateStatusLabel(status: { type: string; error?: string }): string {
  switch (status.type) {
    case 'idle': return 'Up to date'
    case 'checking': return 'Checking...'
    case 'available': return 'Update available'
    case 'downloading': return 'Downloading...'
    case 'installing': return 'Installing...'
    case 'done': return 'Restart required'
    case 'failed': return `Failed: ${status.error ?? 'unknown error'}`
    default: return status.type
  }
}

function statusTone(status: number | null): string {
  if (status == null) return 'bad'
  if (status >= 200 && status < 400) return 'ok'
  return 'bad'
}

function DurationDisplay({ ms }: { ms: number }) {
  const label = ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
  const tone = ms > 5000 ? 'bad' : ms > 1000 ? 'warn' : 'ok'
  return <span className={`font-mono text-[11px] ${tone === 'bad' ? 'text-bad-500' : tone === 'warn' ? 'text-warn-500' : 'text-ok-500'}`}>{label}</span>
}

function ErrorDisplay({ error, stack, devMode }: { error: string; stack?: string; devMode: boolean }) {
  return (
    <div className="text-wrap-safe py-2 text-xs text-bad-500">
      <span>{error}</span>
      {devMode && stack && (
        <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[10px] text-ink-400">{stack}</pre>
      )}
    </div>
  )
}

export function DiagnosticsPage() {
  const store = useAppStore()
  const updateStore = useUpdateStore()
  const [backendInfoState, setBackendInfoState] = useState<SectionLoadState<BackendInfo>>({ data: null, error: null, loading: false })
  const [backendVersion, setBackendVersion] = useState<string>('')
  const [frontendVersion, setFrontendVersion] = useState<string>('')
  const [startupDuration, setStartupDuration] = useState<string>('')
  const [devMode, setDevMode] = useState(false)

  const loadBackendInfo = useCallback(() => {
    setBackendInfoState((s) => ({ ...s, loading: true, error: null }))
    api.info()
      .then((d) => {
        setBackendInfoState({ data: d as unknown as BackendInfo, error: null, loading: false })
        setBackendVersion(d.version ?? '')
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e)
        setBackendInfoState((s) => ({ ...s, error: msg, loading: false }))
      })
  }, [])

  useEffect(() => {
    const start = store.startupStartedAt
    if (start) {
      const elapsed = Math.round((Date.now() - start) / 100) / 10
      setStartupDuration(`${elapsed}s`)
    }
    loadBackendInfo()
    const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
    if (isTauri) {
      invoke<string>('get_app_version').then(setFrontendVersion).catch(() => setFrontendVersion('1.0.0'))
    } else {
      setFrontendVersion('1.0.0 (dev)')
    }
  }, [store.startupStartedAt, loadBackendInfo])

  const ws = getWsClient()
  const metrics = getLastRequestMetrics()
  const requestHistory = getRequestHistory()
  const healthError = getLastHealthCheckError()

  const Row = ({ label, value, tone }: { label: string; value: string; tone?: string }) => (
    <div className="flex items-start justify-between gap-2 border-b border-ink-200/50 py-1.5">
      <span className="shrink-0 font-mono text-[11px] text-ink-500">{label}</span>
      <span className={`text-wrap-safe text-right font-mono text-[11px] ${tone === 'bad' ? 'text-bad-500' : tone === 'ok' ? 'text-ok-500' : tone === 'warn' ? 'text-warn-500' : 'text-ink-700'}`}>{value}</span>
    </div>
  )

  const Section = ({ title, children, onRetry, loading }: { title: string; children: ReactNode; onRetry?: () => void; loading?: boolean }) => (
    <div className="panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-display text-sm font-medium text-ink-700">{title}</h3>
        <div className="flex items-center gap-2">
          {loading && <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink-300 border-t-accent-500" />}
          {onRetry && !loading && (
            <button onClick={onRetry} className="text-[10px] uppercase tracking-wider text-accent-500 hover:text-accent-400 transition-colors">
              Retry
            </button>
          )}
        </div>
      </div>
      {children}
    </div>
  )

  const historyByEndpoint = requestHistory.slice(0).reverse()

  return (
    <div className="mx-auto max-w-4xl px-8 py-10 page-enter">
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <p className="hud-label text-ink-400">Developer</p>
            <h1 className="font-display mt-2 text-display font-medium text-ink-900">Diagnostics</h1>
            <p className="mt-2 text-sm text-ink-500">Runtime diagnostics and system health information</p>
          </div>
          <label className="flex cursor-pointer items-center gap-2">
            <span className="text-[11px] font-medium text-ink-500">Dev Mode</span>
            <div
              className={`relative h-5 w-9 rounded-full transition-colors ${devMode ? 'bg-accent-500' : 'bg-ink-300'}`}
              onClick={() => setDevMode((v) => !v)}
            >
              <div className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${devMode ? 'translate-x-4' : 'translate-x-0'}`} />
            </div>
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Section title="Connection State">
          <Row label="State" value={store.connection.state} tone={store.connection.state === 'connected' ? 'ok' : store.connection.state === 'error' || store.connection.state === 'offline' ? 'bad' : 'warn'} />
          <Row label="Reason" value={store.connection.reason ?? '—'} />
          <Row label="Backend Running" value={String(store.backendRunning)} tone={store.backendRunning ? 'ok' : 'bad'} />
          <Row label="Health OK" value={String(store.healthOk)} tone={store.healthOk ? 'ok' : 'bad'} />
          <Row label="REST OK" value={String(store.restOk)} tone={store.restOk ? 'ok' : 'bad'} />
          <Row label="WS Connected" value={String(store.wsConnected)} tone={store.wsConnected ? 'ok' : 'bad'} />
          <Row label="Health Latency" value={store.healthLatency != null ? `${store.healthLatency}ms` : '—'} />
          <Row label="REST Latency" value={store.restLatency != null ? `${store.restLatency}ms` : '—'} />
          {healthError && (
            <Row label="Health Error" value={healthError.slice(0, 80)} tone="bad" />
          )}
        </Section>

        <Section title="System">
          <Row label="Startup Duration" value={startupDuration || '—'} />
          <Row label="Backend PID" value={store.backendPid != null ? String(store.backendPid) : '—'} />
          <Row label="Backend Version" value={backendVersion || '—'} />
          <Row label="Frontend Version" value={frontendVersion || '—'} />
          <Row label="Update Status" value={updateStatusLabel(updateStore.status)} tone={updateStore.status.type === 'idle' ? 'ok' : updateStore.status.type === 'failed' ? 'bad' : 'warn'} />
          <Row label="Platform" value={navigator.platform} />
          <Row label="User Agent" value={navigator.userAgent.slice(0, 60)} />
        </Section>

        <Section
          title="Backend Info"
          onRetry={loadBackendInfo}
          loading={backendInfoState.loading}
        >
          {backendInfoState.data ? (
            <>
              <Row label="Base Model" value={backendInfoState.data.model.base_model} />
              <Row label="Ollama URL" value={backendInfoState.data.model.ollama_url} />
              <Row label="Provider" value={backendInfoState.data.model.provider} />
              <Row label="Remote Enabled" value={String(backendInfoState.data.model.remote_enabled)} />
              <Row label="Tools" value={`${backendInfoState.data.tools.length} registered`} />
            </>
          ) : backendInfoState.error ? (
            <ErrorDisplay error={backendInfoState.error} devMode={devMode} />
          ) : backendInfoState.loading ? (
            <div className="py-2 text-xs text-ink-400">Loading...</div>
          ) : (
            <div className="py-2 text-xs text-ink-400">No data</div>
          )}
        </Section>

        {metrics && (
          <Section title="Last API Request">
            <Row label="Method" value={metrics.method} />
            <Row label="URL" value={metrics.url} />
            <Row label="Status" value={statusText(metrics.status)} tone={statusTone(metrics.status)} />
            <Row label="Duration" value={`${metrics.latency}ms`} />
            <Row label="Retries" value={String(metrics.retries)} tone={metrics.retries > 0 ? 'warn' : 'ok'} />
            <Row label="Error" value={metrics.error ?? '(none)'} tone={metrics.error ? 'bad' : 'ok'} />
            {devMode && metrics.error && (
              <div className="pt-1">
                <span className="font-mono text-[10px] text-ink-400">Use Request History below for full details</span>
              </div>
            )}
          </Section>
        )}

        {!metrics && (
          <Section title="Last API Request">
            <div className="py-2 text-xs text-ink-400">No requests made yet</div>
          </Section>
        )}

        <Section title="Recent API Calls">
          {historyByEndpoint.length === 0 ? (
            <div className="py-2 text-xs text-ink-400">No requests recorded</div>
          ) : (
            <div className="space-y-1">
              {historyByEndpoint.map((entry, i) => (
                <div key={`${entry.timestamp}-${i}`} className="border-b border-ink-100/50 py-1.5 text-[11px]">
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-ink-700" title={`${entry.method} ${entry.path}`}>
                      <span className="text-ink-400">{entry.method}</span> {entry.path}
                    </span>
                    <DurationDisplay ms={entry.duration} />
                  </div>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span className={`font-mono ${statusTone(entry.status) === 'ok' ? 'text-ok-500' : 'text-bad-500'}`}>{statusText(entry.status)}</span>
                    {entry.retries > 0 && (
                      <span className="font-mono text-warn-500">{entry.retries} retr.{entry.retries > 1 ? 's' : ''}</span>
                    )}
                    <span className="text-ink-300">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                  </div>
                  {entry.error && (
                    <div className={`text-wrap-safe mt-0.5 ${devMode ? '' : 'line-clamp-1'}`}>
                      <span className="font-mono text-[10px] text-bad-500">{entry.error}</span>
                      {devMode && entry.stack && (
                        <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[9px] text-ink-400">{entry.stack}</pre>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="WebSocket">
          <Row label="Connected" value={String(ws.connected)} tone={ws.connected ? 'ok' : 'bad'} />
        </Section>

        <Section title="Updater">
          <Row label="Status" value={updateStatusLabel(updateStore.status)} tone={updateStore.status.type === 'idle' ? 'ok' : updateStore.status.type === 'failed' ? 'bad' : 'warn'} />
          <Row label="Current Version" value={frontendVersion || '—'} />
          <Row label="Last Checked" value={updateStore.lastChecked ? new Date(updateStore.lastChecked).toLocaleString() : '—'} />
          <Row label="Channel" value="stable" />
        </Section>

        <Section title="Environment">
          <Row label="isTauri" value={String(typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window)} />
          <Row label="Port" value="8000" />
          <Row label="DB Path" value={backendInfoState.data ? 'veyron.db (APPDATA)' : 'backend/data/veyron.db'} />
          <Row label="Models Dir" value={backendInfoState.data ? 'models/ (APPDATA)' : 'backend/data/models/'} />
        </Section>
      </div>
    </div>
  )
}
