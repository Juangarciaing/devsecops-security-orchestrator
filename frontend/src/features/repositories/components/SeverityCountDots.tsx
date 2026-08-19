import { cn } from '@/shared/lib/utils'
import type { FindingSeverity } from '@/features/findings/types'
import type { SeverityCounts } from '@/features/trends/types'

const SEVERITY_ORDER: FindingSeverity[] = [
  'critical',
  'high',
  'medium',
  'low',
  'info',
]

const DOT_TOKEN_CLASSNAME: Record<FindingSeverity, string> = {
  critical: 'bg-severity-critical',
  high: 'bg-severity-high',
  medium: 'bg-severity-medium',
  low: 'bg-severity-low',
  info: 'bg-severity-info',
}

// Repositories list table's "Open findings" cell: a most-severe-first dot
// cluster, one dot+count per severity present in `counts`. Absent/zero
// severities are omitted rather than rendered at 0 (Req: repositories list
// mockup) — an empty cluster reads as "No open findings", not a row of
// blank dots.
export function SeverityCountDots({ counts }: { counts: SeverityCounts }) {
  const present = SEVERITY_ORDER.filter(
    (severity) => (counts[severity] ?? 0) > 0,
  )

  if (present.length === 0) {
    return (
      <span className="text-meta text-muted-foreground">No open findings</span>
    )
  }

  return (
    <div className="flex items-center gap-3">
      {present.map((severity) => (
        <span
          key={severity}
          className="text-code inline-flex items-center gap-1.5 tabular-nums"
        >
          <span
            aria-hidden="true"
            className={cn('size-2 rounded-full', DOT_TOKEN_CLASSNAME[severity])}
          />
          {counts[severity]}
          <span className="sr-only">{severity}</span>
        </span>
      ))}
    </div>
  )
}
