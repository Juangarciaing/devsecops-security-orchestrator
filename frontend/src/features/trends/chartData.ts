import type { FindingSeverity } from '@/features/findings/types'
import type { SeverityCounts, TrendPoint } from './types'

// Same severity ordering as `SeverityBadge` (most to least severe) — used as
// the stacking order for the chart's severity series.
export const SEVERITY_ORDER: readonly FindingSeverity[] = [
  'critical',
  'high',
  'medium',
  'low',
  'info',
]

export interface ChartRow extends Record<FindingSeverity, number> {
  scan_run_id: string
  label: string
  occurred_at: string
}

function denseCounts(counts: SeverityCounts): Record<FindingSeverity, number> {
  return {
    critical: counts.critical ?? 0,
    high: counts.high ?? 0,
    medium: counts.medium ?? 0,
    low: counts.low ?? 0,
    info: counts.info ?? 0,
  }
}

// Pure transform: `TrendPoint.introduced` is a sparse dict (absent severity
// implies 0) — flatten each point into a dense row recharts can plot
// directly, one series key per severity. `label` uses the short commit SHA
// as the x-axis tick since scan runs for a repo can land on the same day.
export function toChartRows(points: TrendPoint[]): ChartRow[] {
  return points.map((point) => ({
    scan_run_id: point.scan_run_id,
    label: point.commit_sha.slice(0, 7),
    occurred_at: point.occurred_at,
    ...denseCounts(point.introduced),
  }))
}
