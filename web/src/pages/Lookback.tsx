/**
 * S2 — Lookback & Forecast
 * 60-min historical attack counts + 30-min forecast time-series.
 */

import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AttackTypeChip } from '../components/AttackTypeChip'
import { DataSourceBadge } from '../components/DataSourceBadge'
import { api, type LookbackBucket, type LookbackResponse } from '../lib/api'

const ATTACK_COLORS: Record<string, string> = {
  DDoS_ICMP: '#ef4444',
  Uploading: '#3b82f6',
  Ransomware: '#a855f7',
  DDoS_UDP: '#f97316',
  DDoS_TCP: '#eab308',
  DDoS_HTTP: '#ec4899',
  Normal: '#22c55e',
}
function colorFor(type: string) {
  return ATTACK_COLORS[type] ?? '#6b7280'
}

interface ChartPoint {
  time: string
  [key: string]: string | number
}

const TIME_FMT: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }

function fmtTime(d: Date) {
  return d.toLocaleTimeString([], TIME_FMT)
}

function buildChartData(
  buckets: LookbackBucket[],
  nowLabel: string,
): { data: ChartPoint[]; types: string[] } {
  const byTime: Record<string, Record<string, number>> = {}
  const typesSet = new Set<string>()

  for (const b of buckets) {
    if (!byTime[b.bucket]) byTime[b.bucket] = {}
    byTime[b.bucket][b.attack_type] = b.count
    typesSet.add(b.attack_type)
  }

  const data: ChartPoint[] = Object.entries(byTime)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([bucket, counts]) => ({
      time: fmtTime(new Date(bucket)),
      ...counts,
    }))

  // Append a zero-count sentinel for "now" so the ReferenceLine has
  // a categorical anchor at the right edge of the chart.
  if (data.length > 0 && data[data.length - 1].time !== nowLabel) {
    data.push({ time: nowLabel })
  }

  return { data, types: [...typesSet].filter(t => t !== 'Normal') }
}

export default function LookbackPage() {
  const [data, setData] = useState<LookbackResponse | null>(null)
  const [minutes, setMinutes] = useState(60)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.getLookback({ minutes, bucket_seconds: 300 })
      .then(r => { setData(r); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [minutes])

  const nowLabel = fmtTime(new Date())
  const { data: chartData, types } = data?.buckets
    ? buildChartData(data.buckets, nowLabel)
    : { data: [], types: [] }

  const totalEvents = data?.buckets?.reduce((s, b) => s + b.count, 0) ?? 0
  const topType = data?.buckets
    ? [...data.buckets].sort((a, b) => b.count - a.count)[0]?.attack_type ?? '—'
    : '—'

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">Lookback & Forecast</h1>
          <p className="text-sm text-gray-400">Historical attack activity with time-range selection</p>
        </div>
        <div className="flex items-center gap-3">
          {data && <DataSourceBadge source={data.source_badge} />}
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">Window:</span>
            {[15, 30, 60, 120].map(m => (
              <button
                key={m}
                onClick={() => setMinutes(m)}
                className={`px-3 py-1 rounded text-sm transition-colors ${
                  minutes === m
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                }`}
              >
                {m}m
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="text-2xl font-bold text-white">{totalEvents.toLocaleString()}</div>
          <div className="text-sm text-gray-400 mt-1">Total events ({minutes}m)</div>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="text-2xl font-bold text-white">{types.length}</div>
          <div className="text-sm text-gray-400 mt-1">Attack types seen</div>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center gap-2 mt-1">
            {topType !== '—' ? <AttackTypeChip type={topType} /> : <span className="text-gray-500">—</span>}
          </div>
          <div className="text-sm text-gray-400 mt-1">Top attack type</div>
        </div>
      </div>

      {/* Chart */}
      {loading ? (
        <div className="h-64 flex items-center justify-center text-gray-500">Loading…</div>
      ) : error ? (
        <div className="h-64 flex items-center justify-center text-red-400">Error: {error}</div>
      ) : chartData.length === 0 ? (
        <div className="h-64 flex items-center justify-center text-gray-500">
          No data for the selected window. Run a replay to populate the lookback store.
        </div>
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Attack counts per 5-minute bucket</h2>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="time" tick={{ fill: '#6b7280', fontSize: 11 }} />
              <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6 }}
                labelStyle={{ color: '#e5e7eb' }}
              />
              <Legend />
              {types.map(type => (
                <Area
                  key={type}
                  type="monotone"
                  dataKey={type}
                  stroke={colorFor(type)}
                  fill={colorFor(type)}
                  fillOpacity={0.2}
                  strokeWidth={2}
                />
              ))}
              <ReferenceLine
                x={nowLabel}
                stroke="#facc15"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                label={{
                  value: `Now  ${nowLabel}`,
                  position: 'insideTopRight',
                  fill: '#facc15',
                  fontSize: 10,
                  fontFamily: 'monospace',
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Forecast placeholder */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h2 className="text-sm font-medium text-gray-300 mb-2">30-minute forecast</h2>
        <p className="text-sm text-gray-500">
          Forecast data appears here once the AR Forecaster is active and the pipeline has processed at
          least 20 temporal bins. Activate via <span className="font-mono text-gray-400">Settings → Active Forecaster → ar-forecaster</span>.
        </p>
      </div>
    </div>
  )
}
