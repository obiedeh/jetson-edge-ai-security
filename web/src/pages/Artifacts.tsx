/**
 * S4 — Evidence Artifacts
 * Read-only file browser over reports/, artifacts/, models/exports/.
 */

import { useEffect, useState } from 'react'
import { DataSourceBadge } from '../components/DataSourceBadge'
import { api, type ArtifactInfo } from '../lib/api'
import { cn } from '../lib/utils'

const KIND_COLORS: Record<string, string> = {
  report: 'text-blue-400',
  artifact: 'text-green-400',
  model: 'text-purple-400',
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function JsonViewer({ path }: { path: string }) {
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/artifacts/${encodeURIComponent(path)}`)
      const text = await res.text()
      try {
        const parsed = JSON.parse(text)
        setContent(JSON.stringify(parsed, null, 2))
      } catch {
        setContent(text)
      }
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  if (error) return <div className="text-red-400 text-xs p-2">{error}</div>
  if (loading) return <div className="text-gray-500 text-xs p-2">Loading…</div>
  if (content == null) {
    return (
      <button
        onClick={load}
        className="text-xs text-blue-400 hover:text-blue-300 px-3 py-1"
      >
        View content
      </button>
    )
  }
  return (
    <pre className="overflow-auto max-h-96 p-3 bg-gray-950 rounded text-xs text-gray-300 font-mono">
      {content}
    </pre>
  )
}

export default function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([])
  const [sourceBadge, setSourceBadge] = useState('replay-csv')
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [kindFilter, setKindFilter] = useState<string | null>(null)

  useEffect(() => {
    api.getArtifacts()
      .then(r => {
        setArtifacts(r.artifacts)
        setSourceBadge(r.source_badge)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const toggleExpand = (path: string) =>
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(path) ? next.delete(path) : next.add(path)
      return next
    })

  const filtered = kindFilter ? artifacts.filter(a => a.kind === kindFilter) : artifacts

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Evidence Artifacts</h1>
          <p className="text-sm text-gray-400">reports/, artifacts/, models/exports/</p>
        </div>
        <DataSourceBadge source={sourceBadge} />
      </div>

      {/* Kind filters */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-gray-400">Filter:</span>
        {['report', 'artifact', 'model'].map(k => (
          <button
            key={k}
            onClick={() => setKindFilter(kindFilter === k ? null : k)}
            className={cn(
              'px-3 py-1 rounded text-xs capitalize transition-colors',
              kindFilter === k ? 'bg-gray-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700',
            )}
          >
            {k}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="py-12 text-center text-gray-500">Loading artifacts…</div>
      ) : filtered.length === 0 ? (
        <div className="py-12 text-center text-gray-500">
          No artifacts found. Run a training or replay to generate evidence files.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map(art => (
            <div key={art.path} className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <button
                onClick={() => art.suffix === '.json' || art.suffix === '.jsonl' || art.suffix === '.md'
                  ? toggleExpand(art.path) : undefined}
                className="w-full flex items-center gap-4 px-4 py-3 hover:bg-gray-800/30 transition-colors text-left"
              >
                <span className={cn('text-xs font-medium uppercase w-14 shrink-0', KIND_COLORS[art.kind] ?? 'text-gray-400')}>
                  {art.kind}
                </span>
                <span className="text-sm text-gray-200 font-mono flex-1 truncate">{art.name}</span>
                <span className="text-xs text-gray-500">{art.suffix}</span>
                <span className="text-xs text-gray-500">{formatBytes(art.size_bytes)}</span>
                <span className="text-xs text-gray-600 hidden md:block">
                  {new Date(art.last_modified).toLocaleDateString()}
                </span>
                {(art.suffix === '.json' || art.suffix === '.jsonl' || art.suffix === '.md') && (
                  <span className="text-xs text-blue-400">
                    {expanded.has(art.path) ? '▲' : '▼'}
                  </span>
                )}
              </button>
              {expanded.has(art.path) && (
                <div className="border-t border-gray-800 p-0">
                  <JsonViewer path={art.path} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
