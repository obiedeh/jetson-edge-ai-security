import { cn } from '../lib/utils'

const HIGHLIGHTED = new Set(['DDoS_ICMP', 'Uploading', 'Ransomware'])

const TYPE_COLORS: Record<string, string> = {
  DDoS_ICMP: 'bg-red-900/40 text-red-300 border-red-700',
  Uploading: 'bg-blue-900/40 text-blue-300 border-blue-700',
  Ransomware: 'bg-purple-900/40 text-purple-300 border-purple-700',
  Normal: 'bg-green-900/40 text-green-300 border-green-700',
}

export function AttackTypeChip({ type, active, onClick }: {
  type: string
  active?: boolean
  onClick?: () => void
}) {
  const color = TYPE_COLORS[type] ?? 'bg-gray-800/60 text-gray-300 border-gray-600'
  const isHighlighted = HIGHLIGHTED.has(type)
  return (
    <button
      onClick={onClick}
      className={cn(
        'inline-flex items-center px-2.5 py-1 rounded border text-xs font-mono transition-all',
        color,
        onClick ? 'cursor-pointer hover:brightness-125' : 'cursor-default',
        active ? 'ring-2 ring-white/30' : '',
        isHighlighted ? 'font-semibold' : '',
      )}
    >
      {type}
    </button>
  )
}
