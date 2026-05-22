/**
 * Typed fetch client for the Edge IDS backend API.
 * All paths are relative to /api (proxied to http://localhost:8080 by Vite).
 */

const BASE = '/api'

async function get<T>(path: string, params?: Record<string, string | number | boolean | null | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== null && v !== undefined) url.searchParams.set(k, String(v))
    }
  }
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`)
  return res.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`)
  return res.json()
}

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

export interface AlertRow {
  id: number
  timestamp: string
  attack_type: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  confidence: number
  source: string
  model_run_id: string | null
  payload_json: string
}

export interface AlertsResponse {
  alerts: AlertRow[]
  count: number
  next_cursor: number | null
  source_badge: string
}

export interface LookbackBucket {
  bucket: string
  attack_type: string
  count: number
  avg_confidence: number
}

export interface LookbackResponse {
  minutes: number
  bucket_seconds: number
  buckets: LookbackBucket[]
  source_badge: string
  generated_at: string
}

export interface ForecastResponse {
  forecast: Record<string, unknown> | null
  source_badge: string
  message?: string
}

export interface ModelInfo {
  name: string
  architecture: string
  available: boolean
  active: boolean
  onnx_path: string | null
  metrics: Record<string, number>
  latency: Record<string, number>
  gate?: Record<string, string>
}

export interface ModelsResponse {
  detectors: ModelInfo[]
  forecasters: ModelInfo[]
  active_detector: string
  active_forecaster: string
}

export interface ModelHealthResponse {
  detector: {
    name: string
    train_auc: number | null
    train_f1: number | null
    auc_history: number[]
    moving_avg_auc: number | null
    retrain_auc_floor: number
    retrain_recommended: boolean
    latency: Record<string, number>
    gate: Record<string, string>
  }
  forecaster: {
    name: string
    train_mae: number | null
    mae_reduction_pct: number | null
    latency: Record<string, number>
    gate: Record<string, string>
  }
  recent_model_runs: Record<string, unknown>[]
  source_badge: string
  generated_at: string
}

export interface ArtifactInfo {
  path: string
  relative_path: string
  name: string
  kind: 'report' | 'artifact' | 'model'
  size_bytes: number
  last_modified: string
  suffix: string
}

export interface ArtifactsResponse {
  artifacts: ArtifactInfo[]
  source_badge: string
}

export interface BenchmarkHardware {
  machine?: string
  soc?: string
  device?: string
  jetpack?: string
  tensorrt?: string
  cuda?: string
  lpddr5_gb?: number
  benchmark_started_at?: string | null
}

export interface BenchmarkTier {
  target_rps: number
  actual_rps: number | null
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
}

export interface BenchmarkModel {
  model: string
  onnx?: string
  trt_ep?: boolean
  single_inference_p50_ms?: number | null
  tiers: BenchmarkTier[]
}

export interface BenchmarkGate {
  threshold: number
  measured: number | null
  status: 'pending' | 'pass' | 'fail'
}

export interface BenchmarkRun {
  run_id?: string
  hardware?: BenchmarkHardware | string
  benchmark_finished_at?: string | null
  duration_per_tier_s?: number
  models?: BenchmarkModel[]
  source_badge?: string
  gates?: Record<string, BenchmarkGate>
  note?: string
  [key: string]: unknown
}

export interface BenchmarkRunsResponse {
  runs: BenchmarkRun[]
  source_badge: string
}

// ──────────────────────────────────────────────────────────────────────────────
// API functions
// ──────────────────────────────────────────────────────────────────────────────

export const api = {
  getAlerts: (params?: {
    since?: string
    attack_type?: string
    severity?: string
    source?: string
    limit?: number
    cursor?: number
  }) => get<AlertsResponse>('/alerts', params as Record<string, string | number>),

  getLookback: (params?: { minutes?: number; bucket_seconds?: number }) =>
    get<LookbackResponse>('/lookback', params as Record<string, number>),

  getForecast: () => get<ForecastResponse>('/forecast'),

  getModels: () => get<ModelsResponse>('/models'),

  setActiveModel: (model_type: 'detector' | 'forecaster', model_name: string) =>
    post<{ ok: boolean; model_type: string; model_name: string }>('/models/active', {
      model_type,
      model_name,
    }),

  getModelHealth: () => get<ModelHealthResponse>('/model-health'),

  getArtifacts: () => get<ArtifactsResponse>('/artifacts'),

  getBenchmarkRuns: () => get<BenchmarkRunsResponse>('/benchmark/runs'),

  triggerThorBenchmark: () => post<{ started: boolean; message: string }>('/benchmark/thor', {}),
}
