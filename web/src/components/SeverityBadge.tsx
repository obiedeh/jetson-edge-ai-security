import { cn } from '../lib/utils'

const SEV_CONFIG: Record<string, { color: string; dot: string }> = {
  low: { color: 'text-slate-300 bg-slate-800 border-slate-600', dot: 'bg-slate-400' },
  medium: { color: 'text-yellow-300 bg-yellow-900/40 border-yellow-700', dot: 'bg-yellow-400' },
  high: { color: 'text-orange-300 bg-orange-900/40 border-orange-700', dot: 'bg-orange-400' },
  critical: { color: 'text-red-300 bg-red-900/40 border-red-700 animate-pulse', dot: 'bg-red-400' },
}

export function SeverityBadge({ severity }: { severity: string }) {
  const cfg = SEV_CONFIG[severity] ?? SEV_CONFIG.low
  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-medium uppercase tracking-wide', cfg.color)}>
      <span className={cn('w-1.5 h-1.5 rounded-full', cfg.dot)} />
      {severity}
    </span>
  )
}
