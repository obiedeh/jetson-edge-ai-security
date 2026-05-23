/**
 * S2 — Lookback & Forecast
 * 60-min historical attack counts + 30-min forecast time-series.
 */

import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AttackTypeChip } from '../components/AttackTypeChip'
import { DataSourceBadge } from '../components/DataSourceBadge'
import { api, type ForecastResponse, type LookbackBucket, type LookbackResponse } from '../lib/api'

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
  const [forecast, setForecast] = useState<ForecastResponse | null>(null)
  const [minutes, setMinutes] = useState(60)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Playback state — null playIndex means "show all"
  const [playing, setPlaying] = useState(false)
  const [playIndex, setPlayIndex] = useState<number | null>(null)

  // Fetch lookback on mount, on window change, and every 30 s so new
  // alerts from the demo ticker appear without any user interaction.
  useEffect(() => {
    const fetch = () => {
      setLoading(true)
      setError(null)
      api.getLookback({ minutes, bucket_seconds: 300 })
        .then(r => { setData(r); setLoading(false) })
        .catch(e => { setError(e.message); setLoading(false) })
    }
    fetch()
    const id = setInterval(fetch, 30_000)
    return () => clearInterval(id)
  }, [minutes])

  // Reset playback whenever the window changes
  useEffect(() => {
    setPlaying(false)
    setPlayIndex(null)
  }, [minutes])

  // Forecast: poll every 60 s (backend regenerates every 5 min)
  useEffect(() => {
    api.getForecast().then(setForecast).catch(() => null)
    const id = setInterval(() => {
      api.getForecast().then(setForecast).catch(() => null)
    }, 60_000)
    return () => clearInterval(id)
  }, [])

  // nowLabel ticks every 30 s so the Now reference line stays current
  const [nowLabel, setNowLabel] = useState(() => fmtTime(new Date()))
  useEffect(() => {
    const id = setInterval(() => setNowLabel(fmtTime(new Date())), 30_000)
    return () => clearInterval(id)
  }, [])
  const { data: chartData, types } = data?.buckets
    ? buildChartData(data.buckets, nowLabel)
    : { data: [], types: [] }

  // Advance one bucket every 5 seconds while playing
  useEffect(() => {
    if (!playing || chartData.length === 0) return
    const id = setInterval(() => {
      setPlayIndex(prev => {
        const next = (prev ?? -1) + 1
        if (next >= chartData.length - 1) {
          setPlaying(false)
          return chartData.length - 1
        }
        return next
      })
    }, 5_000)
    return () => clearInterval(id)
  }, [playing, chartData.length])

  const handlePlayPause = () => {
    if (playing) {
      setPlaying(false)
    } else {
      // Restart from beginning if at the end or not started
      const atEnd = playIndex !== null && playIndex >= chartData.length - 1
      if (playIndex === null || atEnd) setPlayIndex(0)
      setPlaying(true)
    }
  }

  const atEnd = playIndex !== null && playIndex >= chartData.length - 1
  const displayData = playIndex !== null ? chartData.slice(0, playIndex + 1) : chartData

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
          {/* Chart heading + play controls */}
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-gray-300">Attack counts per 5-minute bucket</h2>
            <div className="flex items-center gap-2">
              {playIndex !== null && (
                <span className="text-xs font-mono text-gray-400">
                  {displayData[displayData.length - 1]?.time ?? ''} &nbsp;
                  <span className="text-gray-600">{playIndex + 1}/{chartData.length}</span>
                </span>
              )}
              <button
                onClick={handlePlayPause}
                disabled={chartData.length === 0}
                title={playing ? 'Pause' : atEnd ? 'Replay' : 'Play (5 min → 5 sec)'}
                className="flex items-center gap-1.5 px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs font-medium transition-colors disabled:opacity-40"
              >
                {playing
                  ? <><span>⏸</span> Pause</>
                  : atEnd
                  ? <><span>↺</span> Replay</>
                  : <><span>▶</span> Play</>}
              </button>
              {playIndex !== null && !playing && (
                <button
                  onClick={() => { setPlaying(false); setPlayIndex(null) }}
                  title="Exit playback"
                  className="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-500 text-xs transition-colors"
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          {/* Progress bar */}
          {playIndex !== null && (
            <div className="w-full h-0.5 bg-gray-800 rounded mb-3 overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all duration-500"
                style={{ width: `${((playIndex + 1) / chartData.length) * 100}%` }}
              />
            </div>
          )}

          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={displayData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
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

      {/* Forecast panel */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-gray-300">30-minute forecast</h2>
          {forecast?.forecast && (
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="font-mono">{forecast.forecast.payload.active_forecaster}</span>
              <span>generated {new Date(forecast.forecast.generated_at).toLocaleTimeString([], TIME_FMT)}</span>
            </div>
          )}
        </div>

        {!forecast?.forecast ? (
          <p className="text-sm text-gray-500">
            No forecast available yet — the backend generates one every 5 minutes.
            Switch to <span className="font-mono text-gray-400">ar-forecaster</span> in{' '}
            <span className="font-mono text-gray-400">Settings → Active Models</span> for ML-based predictions.
          </p>
        ) : (() => {
          const p = forecast.forecast.payload
          const genAt = new Date(p.generated_at)
          const bins = p.predicted_attack_intensity.map((intensity, i) => {
            const binStart = new Date(genAt.getTime() + (i + 1) * p.bin_seconds * 1000)
            return {
              time: fmtTime(binStart),
              intensity: parseFloat(intensity.toFixed(4)),
              attack_type: p.predicted_attack_type_per_bin[i],
            }
          })

          return (
            <>
              {/* Summary row */}
              <div className="flex flex-wrap gap-4 mb-4">
                <div className="bg-gray-800 rounded px-3 py-2">
                  <div className="text-xs text-gray-500">Overall probability</div>
                  <div className="text-lg font-bold text-white">
                    {(p.probability * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="bg-gray-800 rounded px-3 py-2">
                  <div className="text-xs text-gray-500">Dominant type</div>
                  <div className="mt-1">
                    <AttackTypeChip type={p.attack_type} />
                  </div>
                </div>
                <div className="bg-gray-800 rounded px-3 py-2">
                  <div className="text-xs text-gray-500">Horizon</div>
                  <div className="text-sm font-medium text-gray-200">
                    {fmtTime(genAt)} → {fmtTime(new Date(p.horizon_end))}
                  </div>
                </div>
              </div>

              {/* Per-bin bar chart */}
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={bins} margin={{ top: 4, right: 10, left: -20, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="time" tick={{ fill: '#6b7280', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} domain={[0, 'auto']} />
                  <Tooltip
                    contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 6 }}
                    labelStyle={{ color: '#e5e7eb' }}
                    formatter={(v: number, _n: string, entry) => [
                      `${v.toFixed(4)} (${(entry.payload as {attack_type: string}).attack_type})`,
                      'intensity',
                    ]}
                  />
                  <Bar dataKey="intensity" radius={[3, 3, 0, 0]}>
                    {bins.map((b, i) => (
                      <Cell key={i} fill={colorFor(b.attack_type)} fillOpacity={0.85} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>

              {/* Per-bin type row */}
              <div className="flex gap-2 mt-2 flex-wrap">
                {bins.map((b, i) => (
                  <div key={i} className="flex flex-col items-center gap-0.5">
                    <span className="text-[9px] text-gray-500 font-mono">{b.time}</span>
                    <AttackTypeChip type={b.attack_type} />
                  </div>
                ))}
              </div>
            </>
          )
        })()}
      </div>
    </div>
  )
}
