import { cn } from '../lib/utils'

const BADGE_CONFIG: Record<string, { label: string; color: string }> = {
  'replay-csv': { label: 'CSV Replay', color: 'bg-blue-900/50 text-blue-300 border-blue-700' },
  'replay-pcap': { label: 'PCAP Replay', color: 'bg-purple-900/50 text-purple-300 border-purple-700' },
  'live-mirror': { label: 'Live Mirror', color: 'bg-green-900/50 text-green-300 border-green-700' },
  'validated-thor-benchmark': { label: 'Thor Validated', color: 'bg-amber-900/50 text-amber-300 border-amber-700' },
  'mock': { label: 'Mock Data', color: 'bg-gray-800 text-gray-400 border-gray-600' },
}

export function DataSourceBadge({ source }: { source: string }) {
  const cfg = BADGE_CONFIG[source] ?? { label: source, color: 'bg-gray-800 text-gray-400 border-gray-600' }
  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 rounded border text-xs font-mono', cfg.color)}>
      {cfg.label}
    </span>
  )
}
