/**
 * S3 — Model Health
 * AUC sparkline, F1 score, FPR, retrain flag when AUC drifts below threshold.
 */

import { useEffect, useState } from 'react'
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import { DataSourceBadge } from '../components/DataSourceBadge'
import { api, type ModelHealthResponse } from '../lib/api'
import { cn } from '../lib/utils'

function GateBadge({ result }: { result?: string }) {
  if (!result) return null
  return (
    <span className={cn(
      'px-2 py-0.5 rounded text-xs font-medium ml-2',
      result === 'PASS' ? 'bg-green-900/50 text-green-300 border border-green-700' : 'bg-red-900/50 text-red-300 border border-red-700',
    )}>
      Gate: {result}
    </span>
  )
}

function MetricCard({ label, value, unit }: { label: string; value: string | number | null; unit?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="text-2xl font-bold text-white">
        {value != null ? `${value}${unit ?? ''}` : '—'}
      </div>
      <div className="text-xs text-gray-400 mt-1">{label}</div>
    </div>
  )
}

function SparklineChart({ data }: { data: number[] }) {
  if (!data.length) return <div className="h-8 flex items-center text-xs text-gray-500">No history</div>
  const pts = data.map((v, i) => ({ i, v }))
  return (
    <ResponsiveContainer width="100%" height={48}>
      <LineChart data={pts} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
        <Line type="monotone" dataKey="v" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
        <Tooltip
          contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 4, fontSize: 11 }}
          formatter={(v) => [typeof v === 'number' ? v.toFixed(4) : String(v), 'AUC']}
          labelFormatter={() => ''}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function ModelHealthPage() {
  const [health, setHealth] = useState<ModelHealthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getModelHealth()
      .then(r => { setHealth(r); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  if (loading) return <div className="py-20 text-center text-gray-500">Loading model health…</div>
  if (error) return <div className="py-20 text-center text-red-400">Error: {error}</div>
  if (!health) return null

  const det = health.detector
  const fcast = health.forecaster

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Model Health</h1>
          <p className="text-sm text-gray-400">Drift KPI, performance gates, retrain signal</p>
        </div>
        <DataSourceBadge source={health.source_badge} />
      </div>

      {det.retrain_recommended && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 flex items-start gap-3">
          <span className="text-red-400 text-xl">⚠</span>
          <div>
            <div className="font-semibold text-red-300">Retrain Recommended</div>
            <div className="text-sm text-red-400 mt-1">
              Moving-average AUC ({det.moving_avg_auc?.toFixed(4) ?? '—'}) has fallen below the
              floor of {det.retrain_auc_floor.toFixed(2)}.
              Run <span className="font-mono">edge-security train detector</span> to refresh.
            </div>
          </div>
        </div>
      )}

      <section>
        <h2 className="text-base font-semibold text-gray-200 mb-3 flex items-center">
          Detector — {det.name}
          <GateBadge result={det.gate?.result} />
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <MetricCard label="Training AUC" value={det.train_auc?.toFixed(4) ?? null} />
          <MetricCard label="F1 Score" value={det.train_f1?.toFixed(4) ?? null} />
          <MetricCard label="p50 Latency" value={det.latency?.p50_ms?.toFixed(2) ?? null} unit=" ms" />
          <MetricCard label="p95 Latency" value={det.latency?.p95_ms?.toFixed(2) ?? null} unit=" ms" />
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-400">AUC History (model runs)</span>
            <span className="text-xs text-gray-400">Floor: {det.retrain_auc_floor.toFixed(2)}</span>
          </div>
          <SparklineChart data={det.auc_history} />
          {!det.auc_history.length && (
            <p className="text-xs text-gray-500 mt-2">
              AUC history populates as training runs complete and are registered
              via <span className="font-mono">edge-security train detector</span>.
            </p>
          )}
        </div>
      </section>

      <section>
        <h2 className="text-base font-semibold text-gray-200 mb-3 flex items-center">
          Forecaster — {fcast.name}
          <GateBadge result={fcast.gate?.result} />
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricCard label="Ridge MAE" value={fcast.train_mae?.toFixed(3) ?? null} />
          <MetricCard label="MAE Reduction" value={fcast.mae_reduction_pct?.toFixed(1) ?? null} unit="%" />
          <MetricCard label="p50 Latency" value={fcast.latency?.p50_ms?.toFixed(2) ?? null} unit=" ms" />
          <MetricCard label="p95 Latency" value={fcast.latency?.p95_ms?.toFixed(2) ?? null} unit=" ms" />
        </div>
      </section>

      {health.recent_model_runs.length > 0 && (
        <section>
          <h2 className="text-base font-semibold text-gray-200 mb-3">Recent Model Runs</h2>
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-400 text-left">
                  <th className="px-4 py-3 font-medium">Run ID</th>
                  <th className="px-4 py-3 font-medium">Started</th>
                  <th className="px-4 py-3 font-medium">AUC</th>
                  <th className="px-4 py-3 font-medium">F1</th>
                </tr>
              </thead>
              <tbody>
                {health.recent_model_runs.map((r, i) => (
                  <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-300">{String(r.id ?? '—')}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-400">
                      {r.started_at ? new Date(String(r.started_at)).toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-300">{r.auc != null ? Number(r.auc).toFixed(4) : '—'}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-300">{r.f1 != null ? Number(r.f1).toFixed(4) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
