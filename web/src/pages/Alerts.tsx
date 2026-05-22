/**
 * S1 — Live Alerts
 * Real-time SSE stream of new alerts, with filter chips for the three
 * high-signal attack categories.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { AttackTypeChip } from '../components/AttackTypeChip'
import { DataSourceBadge } from '../components/DataSourceBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { api, type AlertRow } from '../lib/api'
import { connectAlertStream, type AlertPayload } from '../lib/sse'
import { cn } from '../lib/utils'

const FILTER_TYPES = ['DDoS_ICMP', 'Uploading', 'Ransomware', 'Other']
const MAX_LIVE = 200

function parsePayload(json: string): Record<string, unknown> {
  try { return JSON.parse(json) } catch { return {} }
}

function confidenceBar(c: number) {
  const pct = Math.round(c * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded bg-gray-700">
        <div
          className={cn('h-full rounded', c > 0.8 ? 'bg-red-500' : c > 0.5 ? 'bg-yellow-500' : 'bg-blue-500')}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-400">{pct}%</span>
    </div>
  )
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [liveAlerts, setLiveAlerts] = useState<AlertPayload[]>([])
  const [activeFilter, setActiveFilter] = useState<string | null>(null)
  const [sourceBadge, setSourceBadge] = useState('replay-csv')
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const sseCleanup = useRef<(() => void) | null>(null)

  // Initial load
  useEffect(() => {
    api.getAlerts({ limit: 50 }).then(r => {
      setAlerts(r.alerts)
      setSourceBadge(r.source_badge)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  // SSE connection
  useEffect(() => {
    const cleanup = connectAlertStream(
      (payload) => {
        setConnected(true)
        setLiveAlerts(prev => [payload, ...prev].slice(0, MAX_LIVE))
      },
      () => setConnected(true),
      () => setConnected(false),
    )
    sseCleanup.current = cleanup
    return () => cleanup()
  }, [])

  const toggleFilter = useCallback((t: string) => {
    setActiveFilter(prev => (prev === t ? null : t))
  }, [])

  const allAlerts: (AlertRow | AlertPayload)[] = [
    ...liveAlerts.map(a => ({ ...a, _live: true } as unknown as AlertRow)),
    ...alerts,
  ]

  const filtered = allAlerts.filter(a => {
    if (!activeFilter) return true
    const type = (a as AlertRow).attack_type ?? ''
    if (activeFilter === 'Other') return !['DDoS_ICMP', 'Uploading', 'Ransomware'].includes(type)
    return type === activeFilter
  })

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Live Alerts</h1>
          <p className="text-sm text-gray-400">Real-time intrusion detection events</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn('w-2 h-2 rounded-full', connected ? 'bg-green-400 animate-pulse' : 'bg-gray-500')} />
          <span className="text-xs text-gray-400">{connected ? 'Connected' : 'Disconnected'}</span>
          <DataSourceBadge source={sourceBadge} />
        </div>
      </div>

      {/* Mock source banner */}
      {sourceBadge === 'mock' && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded p-3 text-yellow-300 text-sm">
          Mock source — does not reflect real or replayed network traffic. Use only for UI development.
        </div>
      )}

      {/* Filter chips */}
      <div className="flex flex-wrap gap-2">
        {FILTER_TYPES.map(t => (
          <AttackTypeChip
            key={t}
            type={t}
            active={activeFilter === t}
            onClick={() => toggleFilter(t)}
          />
        ))}
        {activeFilter && (
          <button
            onClick={() => setActiveFilter(null)}
            className="text-xs text-gray-400 hover:text-white px-2"
          >
            × Clear
          </button>
        )}
      </div>

      {/* Alert count */}
      <div className="text-xs text-gray-500">
        {liveAlerts.length > 0 && (
          <span className="text-green-400 mr-2">+{liveAlerts.length} live</span>
        )}
        {filtered.length} total shown
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading alerts…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-gray-500">No alerts yet. Start a replay to see events.</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-400 text-left">
                <th className="px-4 py-3 font-medium">Time</th>
                <th className="px-4 py-3 font-medium">Attack Type</th>
                <th className="px-4 py-3 font-medium">Severity</th>
                <th className="px-4 py-3 font-medium">Confidence</th>
                <th className="px-4 py-3 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a, i) => {
                const row = a as AlertRow & { _live?: boolean }
                return (
                  <tr
                    key={row.id ?? `live-${i}`}
                    className={cn(
                      'border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors',
                      row._live ? 'bg-green-900/10' : '',
                    )}
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-400">
                      {row.timestamp ? new Date(row.timestamp).toLocaleTimeString() : '—'}
                      {row._live && <span className="ml-1 text-green-400 text-xs">●</span>}
                    </td>
                    <td className="px-4 py-2.5">
                      <AttackTypeChip type={row.attack_type ?? 'Unknown'} />
                    </td>
                    <td className="px-4 py-2.5">
                      <SeverityBadge severity={row.severity ?? 'low'} />
                    </td>
                    <td className="px-4 py-2.5">
                      {row.confidence != null ? confidenceBar(row.confidence) : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      <DataSourceBadge source={row.source ?? 'replay-csv'} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
