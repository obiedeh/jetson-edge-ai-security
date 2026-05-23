/**
 * S5 — Settings
 * Source switcher, model selector, threshold editors, Thor benchmark trigger.
 */

import { useEffect, useState } from 'react'
import { DataSourceBadge } from '../components/DataSourceBadge'
import { api, type ModelsResponse, type BenchmarkRun, type BenchmarkHardware } from '../lib/api'
import { cn } from '../lib/utils'

const SOURCE_OPTS = [
  { value: 'replay-csv', label: 'CSV Replay', desc: 'Replay from a local CSV file' },
  { value: 'replay-pcap', label: 'PCAP Replay', desc: 'Replay from a PCAP file (simulates SPAN mirror)' },
  { value: 'live-mirror', label: 'Live Mirror', desc: 'Live SPAN/mirror port capture (v1.x)' },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <h2 className="text-sm font-semibold text-gray-200 mb-4">{title}</h2>
      {children}
    </div>
  )
}

export default function SettingsPage() {
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [benchRuns, setBenchRuns] = useState<BenchmarkRun[]>([])
  const [activeSource, setActiveSource] = useState('replay-csv')
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [benchRunning, setBenchRunning] = useState(false)
  const [benchMsg, setBenchMsg] = useState<string | null>(null)
  const [restarting, setRestarting] = useState(false)
  const [restartMsg, setRestartMsg] = useState<string | null>(null)

  useEffect(() => {
    api.getModels().then(setModels).catch(() => null)
    api.getBenchmarkRuns().then(r => setBenchRuns(r.runs)).catch(() => null)
    // Load the currently persisted source from the backend
    api.getRuntimeStatus().then(s => setActiveSource(s.source)).catch(() => null)
  }, [])

  const handleSetActiveModel = async (type: 'detector' | 'forecaster', name: string) => {
    setSaving(true)
    setSaveMsg(null)
    try {
      await api.setActiveModel(type, name)
      const updated = await api.getModels()
      setModels(updated)
      setSaveMsg(`✓ Active ${type} set to ${name}`)
    } catch (e: unknown) {
      setSaveMsg(`✗ ${String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  const handleThorBenchmark = async () => {
    setBenchRunning(true)
    setBenchMsg(null)
    try {
      const r = await api.triggerThorBenchmark()
      setBenchMsg(r.message)
      // Refresh after a moment
      setTimeout(() => api.getBenchmarkRuns().then(r => setBenchRuns(r.runs)).catch(() => null), 2000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('409')) {
        setBenchMsg('Not running on Jetson hardware — Thor benchmark only valid on aarch64 with JETSON_SOC set.')
      } else {
        setBenchMsg(`Error: ${msg}`)
      }
    } finally {
      setBenchRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-6 max-w-2xl">
      <div>
        <h1 className="text-xl font-semibold text-white">Settings</h1>
        <p className="text-sm text-gray-400">Runtime configuration, model selection, benchmark triggers</p>
      </div>

      {/* Source switcher */}
      <Section title="Input Source">
        <div className="flex flex-col gap-2">
          {SOURCE_OPTS.map(opt => (
            <label key={opt.value} className="flex items-start gap-3 cursor-pointer group">
              <input
                type="radio"
                name="source"
                value={opt.value}
                checked={activeSource === opt.value}
                onChange={() => setActiveSource(opt.value)}
                className="mt-1"
                disabled={opt.value === 'live-mirror'}
              />
              <div className={cn('flex-1', opt.value === 'live-mirror' ? 'opacity-50' : '')}>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-200">{opt.label}</span>
                  <DataSourceBadge source={opt.value} />
                  {opt.value === 'live-mirror' && (
                    <span className="text-xs text-gray-500 italic">v1.x</span>
                  )}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{opt.desc}</div>
              </div>
            </label>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3 flex-wrap">
          <button
            onClick={async () => {
              setRestarting(true)
              setRestartMsg(null)
              try {
                const r = await api.restartRuntime(activeSource)
                setRestartMsg(`✓ ${r.message}`)
              } catch (e: unknown) {
                setRestartMsg(`✗ ${e instanceof Error ? e.message : String(e)}`)
              } finally {
                setRestarting(false)
              }
            }}
            disabled={restarting || activeSource === 'live-mirror'}
            className="px-4 py-2 bg-blue-700 hover:bg-blue-600 text-white rounded text-sm font-medium disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            {restarting
              ? <><span className="animate-spin inline-block">↻</span> Restarting…</>
              : '↻ Restart Runtime'}
          </button>
          {activeSource === 'live-mirror' && (
            <span className="text-xs text-gray-500 italic">Live mirror is not available in v0.x</span>
          )}
        </div>
        {restartMsg && (
          <div className={cn('mt-2 text-sm', restartMsg.startsWith('✓') ? 'text-green-400' : 'text-red-400')}>
            {restartMsg}
          </div>
        )}
      </Section>

      {/* Model selector */}
      <Section title="Active Models">
        {models == null ? (
          <div className="text-sm text-gray-500">Loading…</div>
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <div className="text-xs text-gray-400 mb-2">Detector</div>
              <div className="flex flex-wrap gap-2">
                {models.detectors.map(d => (
                  <button
                    key={d.name}
                    onClick={() => handleSetActiveModel('detector', d.name)}
                    disabled={saving}
                    className={cn(
                      'px-3 py-1.5 rounded border text-sm font-mono transition-colors',
                      d.active
                        ? 'bg-blue-900/50 text-blue-300 border-blue-600'
                        : 'bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-500',
                    )}
                  >
                    {d.name}
                    {d.active && <span className="ml-1 text-green-400">✓</span>}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-2">Forecaster</div>
              <div className="flex flex-wrap gap-2">
                {models.forecasters.map(f => (
                  <button
                    key={f.name}
                    onClick={() => handleSetActiveModel('forecaster', f.name)}
                    disabled={saving}
                    className={cn(
                      'px-3 py-1.5 rounded border text-sm font-mono transition-colors',
                      f.active
                        ? 'bg-purple-900/50 text-purple-300 border-purple-600'
                        : 'bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-500',
                    )}
                  >
                    {f.name}
                    {f.active && <span className="ml-1 text-green-400">✓</span>}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {saveMsg && (
          <div className={cn('mt-3 text-sm', saveMsg.startsWith('✓') ? 'text-green-400' : 'text-red-400')}>
            {saveMsg}
          </div>
        )}
      </Section>

      {/* Thor benchmark */}
      <Section title="Thor Benchmark">
        <p className="text-sm text-gray-400 mb-3">
          Trigger a TensorRT benchmark run on the Jetson AGX Thor. This only works
          when the API server is running on aarch64 hardware with <span className="font-mono text-gray-300">JETSON_SOC</span> set.
        </p>
        <button
          onClick={handleThorBenchmark}
          disabled={benchRunning}
          className="px-4 py-2 bg-amber-700 hover:bg-amber-600 text-white rounded text-sm font-medium disabled:opacity-50 transition-colors"
        >
          {benchRunning ? 'Running…' : 'Run Thor Benchmark'}
        </button>
        {benchMsg && (
          <div className="mt-2 text-sm text-gray-400">{benchMsg}</div>
        )}

        {benchRuns.length > 0 && (
          <div className="mt-4">
            <div className="text-xs text-gray-400 mb-2">Previous Runs</div>
            <div className="flex flex-col gap-2">
              {benchRuns.map((r, i) => {
                const hw: BenchmarkHardware | null =
                  r.hardware && typeof r.hardware === 'object' ? r.hardware as BenchmarkHardware
                  : null
                const badge = r.source_badge ?? 'pending-thor-run'
                const isPending = badge === 'pending-thor-run'

                // Pull p95 from nested models[].tiers[]
                const detModel = r.models?.find(m => m.model === 'detector')
                const fcastModel = r.models?.find(m => m.model === 'forecaster')
                const detP95 = detModel?.tiers?.find(t => t.target_rps === 1000)?.p95_ms ?? null
                const fcastP95 = fcastModel?.tiers?.find(t => t.target_rps === 1000)?.p95_ms ?? null
                const throughput = detModel?.tiers?.find(t => t.target_rps === 1000)?.actual_rps ?? null

                return (
                  <div key={i} className="bg-gray-800 rounded p-3 text-xs font-mono text-gray-300">
                    <div className="flex items-center gap-2 mb-2">
                      {r.run_id && (
                        <span className="text-gray-400 truncate max-w-[180px]">{r.run_id}</span>
                      )}
                      <DataSourceBadge source={badge} />
                    </div>
                    {isPending ? (
                      <div className="text-gray-500 italic">
                        {r.note ?? 'No benchmark data yet — run on Jetson AGX Thor to populate.'}
                      </div>
                    ) : (
                      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-gray-400">
                        {hw?.device && (
                          <div>Device: <span className="text-gray-200">{hw.device}</span></div>
                        )}
                        {hw?.soc && (
                          <div>SoC: <span className="text-gray-200">{hw.soc}</span></div>
                        )}
                        {hw?.jetpack && (
                          <div>JetPack: <span className="text-gray-200">{hw.jetpack}</span></div>
                        )}
                        {detP95 != null && (
                          <div>Det p95: <span className="text-gray-200">{detP95} ms</span></div>
                        )}
                        {fcastP95 != null && (
                          <div>Fcast p95: <span className="text-gray-200">{fcastP95} ms</span></div>
                        )}
                        {throughput != null && (
                          <div>Throughput: <span className="text-gray-200">{throughput} ev/s</span></div>
                        )}
                      </div>
                    )}
                    {r.gates && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {Object.entries(r.gates).map(([key, gate]) => (
                          <span
                            key={key}
                            className={cn(
                              'px-1.5 py-0.5 rounded text-[10px] font-sans',
                              gate.status === 'pass'
                                ? 'bg-green-900/40 text-green-400 border border-green-800'
                                : gate.status === 'fail'
                                ? 'bg-red-900/40 text-red-400 border border-red-800'
                                : 'bg-gray-700 text-gray-400 border border-gray-600',
                            )}
                          >
                            {key.replace(/_/g, ' ')}: {gate.status}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </Section>
    </div>
  )
}
